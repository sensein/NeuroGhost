"""
export_json.py — Export registry snapshot + provenance to data/
---------------------------------------------------------------
Runs after every ingest/align cycle. Produces:

  data/registry.json          — latest snapshot (frontend reads this)
  data/versions/{ver}.json    — archived snapshot for this registry version
  data/provenance.json        — append-only log of every registry version

Usage:
    python export_json.py
    python export_json.py --db ./registry.lbug --bump minor
    python export_json.py --issue 3 --agent sulimansharif --bump minor
"""

from __future__ import annotations
import json, shutil
from pathlib import Path

import click

from db import (
    get_connection, now_iso,
    current_registry_version, next_registry_version, append_provenance,
    PROVENANCE_PATH,
)

DATA_DIR = Path("data")
DB_PATH  = "./registry.lbug"


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _attesting_sources(conn, label: str, rel: str, id: str) -> list[str]:
    """Every distinct source that has a ProvenanceEntry for this entity."""
    return sorted({
        r[0] for r in conn.execute(f"""
            MATCH (:{label} {{id: $node_id}})-[:{rel}]->(:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(ss:SchemaSource)
            RETURN ss.label
        """, {"node_id": id}).get_all()
    })


# Display order of a property's rules.
_RULE_ORDER = ("RANGE", "REQUIRED", "PATTERN", "MIN_VALUE", "MAX_VALUE", "UNIT")


Rule = tuple[str, str, "str | None", frozenset]  # type, value, used_in_class id, source labels


def _load_rules(conn) -> dict[str, list[Rule]]:
    """Every rule on a property, as property id -> [(rule_type, rule_value,
    used_in_class id or None, labels of the sources that state it)]. One
    query for the whole export."""
    found: dict[tuple, set] = {}
    for prop_id, rid, rule_type, rule_value, class_id, source in conn.execute("""
        MATCH (rr:RegistryRule)-[:APPLIES_TO_P]->(p:RegistryProperty)
        OPTIONAL MATCH (rr)-[:USED_IN_CLASS]->(c:RegistryClass)
        OPTIONAL MATCH (rr)-[:HAS_PROVENANCE_R]->(:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(s:SchemaSource)
        RETURN p.id, rr.id, rr.rule_type, rr.rule_value, c.id, s.label
    """).get_all():
        if rule_type and rule_value is not None:
            found.setdefault((prop_id, rid, rule_type, rule_value, class_id), set()).add(source)
    by_prop: dict[str, list[Rule]] = {}
    for (prop_id, _, rule_type, rule_value, class_id), sources in found.items():
        by_prop.setdefault(prop_id, []).append(
            (rule_type, rule_value, class_id, frozenset(sources - {None})))
    return by_prop


def _effective_rules(rules: list[Rule], class_id: str, class_sources: set[str],
                     names: dict[str, str]) -> list[dict]:
    """The rules in effect for a property used inside one class: per
    rule_type, the class-scoped rules (used_in_class = this class) if any,
    else the schema-level ones (used_in_class unset) — see RegistryRule in
    meta_model.yaml. A property can be shared by several schemas, each with
    its own schema-level rules, so only rules stated by a source that also
    defines this class count. `scope` says class vs schema; `label` is the
    value made readable (a RANGE to a class or value set holds its id)."""
    rules = [r for r in rules if r[3] & class_sources]
    effective = []
    for rule_type in sorted({r[0] for r in rules},
                            key=lambda t: (_RULE_ORDER.index(t) if t in _RULE_ORDER else 99, t)):
        scoped = sorted({v for t, v, c, _ in rules if t == rule_type and c == class_id})
        shared = sorted({v for t, v, c, _ in rules if t == rule_type and c is None})
        values, scope = (scoped, "class") if scoped else (shared, "schema")
        effective += [{"type": rule_type, "value": v, "label": names.get(v, v), "scope": scope}
                      for v in values]
    return effective


_PREDICATE_CURIE = {
    "EXACT_MATCH": "skos:exactMatch", "CLOSE_MATCH": "skos:closeMatch",
    "BROAD_MATCH": "skos:broadMatch", "NARROW_MATCH": "skos:narrowMatch",
    "RELATED_MATCH": "skos:relatedMatch", "EQUIVALENT_CLASS": "owl:equivalentClass",
}


def _load_mappings(conn, names: dict[str, str]) -> dict[str, list[dict]]:
    """Every Mapping (loaded from mappings/*.sssom.tsv), as subject id ->
    [mapping dict], with who proposed it (tool, justification) and who
    reviewed it read from its MappingProvenanceEntry nodes."""
    prov: dict[str, dict] = {}
    for mid, activity, agent, tool, just, at in conn.execute("""
        MATCH (e:MappingProvenanceEntry)
        RETURN e.attests_to, e.was_generated_by, e.was_attributed_to,
               e.mapping_tool, e.mapping_justification, e.generated_at_time
    """).get_all():
        p = prov.setdefault(mid, {})
        if activity == "review":
            p.update(reviewed_by=agent or "", reviewed_at=at or "")
        else:
            p.update(proposed_by=agent or "", proposed_at=at or "",
                     mapping_tool=tool or "", mapping_justification=just or "")

    by_subject: dict[str, list[dict]] = {}
    for rel, label in (("HAS_SKOS_MAPPING", "RegistryClass"), ("HAS_SKOS_MAPPING_P", "RegistryProperty")):
        for sid, mid, mtype, target, conf, status, mset in conn.execute(f"""
            MATCH (s:{label})-[:{rel}]->(m:Mapping)
            RETURN s.id, m.id, m.mapping_type, m.target, m.confidence,
                   m.review_status, m.mapping_set_id
        """).get_all():
            by_subject.setdefault(sid, []).append({
                "id": mid,
                "predicate": _PREDICATE_CURIE.get(mtype, mtype or ""),
                "target_id": target or "",
                "target_name": names.get(target, ""),
                # Stored as a 32-bit FLOAT: round off the float noise.
                "confidence": None if conf is None else round(conf, 3),
                "review_status": status or "PROPOSED",
                "mapping_set_id": mset or "",
                **{"proposed_by": "", "mapping_tool": "", "mapping_justification": "",
                   "reviewed_by": "", **prov.get(mid, {})},
            })
    for ms in by_subject.values():
        ms.sort(key=lambda m: (m["target_name"], m["mapping_set_id"]))
    return by_subject


def export_snapshot(conn, registry_version: str) -> dict:
    def _class_count_where(clause: str, params: dict) -> int:
        return conn.execute(f"""
            MATCH (n:RegistryClass)-[:HAS_PROVENANCE]->(:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(s:SchemaSource)
            WHERE {clause}
            RETURN count(DISTINCT n)
        """, params).get_next()[0]

    # ---- sources (physical files, each part_of a bundle) -------------------
    src_rows = conn.execute("""
        MATCH (s:SchemaSource)
        OPTIONAL MATCH (b:SchemaBundle) WHERE b.id = s.part_of
        RETURN s.label, b.label, s.title, s.description, s.homepage,
               s.source_id, s.source_iri, s.source_version, s.mime_type,
               s.content_hash, s.created_at, s.registry_version
    """).get_all()
    sources = []
    src_versions: dict[str, set] = {}
    for (label, bundle_label, title, desc, homepage, source_id, source_iri,
         ver, mime_type, content_hash, created_at, reg_ver) in src_rows:
        if bundle_label:
            src_versions.setdefault(bundle_label, set()).add(ver or "")
        sources.append({
            "label": label, "bundle": bundle_label or "", "version": ver or "1.0.0",
            "title": title or "", "description": desc or "", "homepage": homepage or "",
            # Per-file provenance: where this physical file came from.
            "source_id": source_id or "", "source_iri": source_iri or "",
            "class_count": _class_count_where("s.label = $v", {"v": label}),
            "mime_type": mime_type or "", "created_at": created_at or "",
            "registry_version": reg_ver or "",
            # File-level fingerprint so the UI can pre-check a dropped/pasted
            # schema against sources already in the registry (see schema_hash.py).
            "content_hash": content_hash or "",
        })

    # ---- bundles (logical schemas; the metadata SHARED across files lives here;
    #      per-file provenance is on the sources above) -----------------------
    bnd_rows = conn.execute("""
        MATCH (b:SchemaBundle)
        RETURN b.id, b.label, b.title, b.description,
               b.publisher, b.contact, b.homepage, b.license, b.created_at
    """).get_all()
    bundles = []
    for (bid, label, title, desc,
         publisher, contact, homepage, lic, created_at) in bnd_rows:
        parts = sorted(r[0] for r in conn.execute(
            "MATCH (s:SchemaSource) WHERE s.part_of = $id RETURN s.label", {"id": bid}).get_all())
        # A bundle version to show in the header only when its files agree on one.
        vers = {v for v in src_versions.get(label, set()) if v}
        bundles.append({
            "label": label, "title": title or "", "description": desc or "",
            "version": (vers.pop() if len(vers) == 1 else ""),
            "publisher": publisher or "", "contact": contact or "",
            "homepage": homepage or "", "license": lic or "", "created_at": created_at or "",
            "parts": parts,
            "class_count": _class_count_where("s.part_of = $id", {"id": bid}),
        })

    # ---- classes -----------------------------------------------------------
    # Identity is shared across sources now, so a class/property no longer
    # has a single "source" — it has a `sources` list, one per ProvenanceEntry.
    cls_rows = conn.execute("""
        MATCH (n:RegistryClass)
        RETURN n.id, n.sha256_hash, n.concept_uri, n.name, n.description, n.is_abstract
        ORDER BY n.name
    """).get_all()

    rules_by_prop = _load_rules(conn)
    # id -> name for the entities a RANGE rule or a Mapping can point at.
    names = {
        i: n for label in ("RegistryClass", "RegistryValueSet", "RegistryProperty")
        for i, n in conn.execute(f"MATCH (x:{label}) RETURN x.id, x.name").get_all()
    }
    mappings_by_subject = _load_mappings(conn, names)

    classes = []
    for row in cls_rows:
        node_id, sha256_hash, concept_uri, name, desc, is_abstract = row
        class_sources = _attesting_sources(conn, "RegistryClass", "HAS_PROVENANCE", node_id)

        props = conn.execute("""
            MATCH (c:RegistryClass {id: $id})-[:HAS_PROPERTY]->(p:RegistryProperty)
            RETURN p.id, p.sha256_hash, p.concept_uri, p.name, p.description
            ORDER BY p.name
        """, {"id": node_id}).get_all()

        subclass_of = [
            r[0] for r in conn.execute("""
                MATCH (c:RegistryClass {id: $id})-[:SUBCLASS_OF]->(p:RegistryClass)
                RETURN p.concept_uri
            """, {"id": node_id}).get_all() if r[0]
        ]

        align_rows = conn.execute("""
            MATCH (c:RegistryClass {id: $id})-[a:ALIGNED_TO]->(t:RegistryClass)
            RETURN t.id, t.name, t.concept_uri,
                   a.distance, a.method,
                   a.score_iri, a.score_name, a.score_desc, a.score_slot
            ORDER BY a.distance
        """, {"id": node_id}).get_all()

        classes.append({
            "id":               node_id,
            "sha256_hash":      sha256_hash or "",
            "iri":              concept_uri or "",
            "name":             name or "",
            "definition":       desc or "",
            "is_abstract":      bool(is_abstract),
            "sources":          class_sources,
            "properties": [
                {
                    "id":          r[0],
                    "sha256_hash": r[1] or "",
                    "iri":         r[2] or "",
                    "name":        r[3] or "",
                    "definition":  r[4] or "",
                    # The rules in effect for this property in THIS class
                    # (range, required, pattern, ...): schema-level, or this
                    # class's own where it constrains the property differently.
                    "rules":       rules,
                    # Value type and unit live on RANGE/UNIT rules, not on the
                    # property node — kept as flat strings for older readers.
                    "value_range": " | ".join(x["label"] for x in rules if x["type"] == "RANGE"),
                    "units":       " | ".join(x["value"] for x in rules if x["type"] == "UNIT"),
                    "sources":     _attesting_sources(conn, "RegistryProperty", "HAS_PROVENANCE_P", r[0]),
                    "mappings":    mappings_by_subject.get(r[0], []),
                }
                for r in props
                for rules in [_effective_rules(rules_by_prop.get(r[0], []), node_id,
                                               set(class_sources), names)]
            ],
            "subclass_of": subclass_of,
            "mappings":    mappings_by_subject.get(node_id, []),
            "alignments": [
                {
                    "target_id": r[0],
                    "target_name":    r[1] or "",
                    "target_iri":     r[2] or "",
                    "distance":       float(r[3]) if r[3] is not None else 1.0,
                    "method":         r[4] or "",
                    "scores": {
                        "iri":  float(r[5]) if r[5] is not None else 0.0,
                        "name": float(r[6]) if r[6] is not None else 0.0,
                        "desc": float(r[7]) if r[7] is not None else 0.0,
                        "slot": float(r[8]) if r[8] is not None else 0.0,
                    }
                }
                for r in align_rows
            ],
        })

    return {
        "registry_version": registry_version,
        "generated_at":     now_iso(),
        "bundles":          bundles,
        "sources":          sources,
        "classes":          classes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--db",     default=DB_PATH, show_default=True)
@click.option("--bump",   default="minor",
              type=click.Choice(["major", "minor", "patch"]),
              help="Version bump type. major=breaking, minor=new schema, patch=update.")
@click.option("--issue",  default="", help="GitHub issue number that triggered this.")
@click.option("--agent",  default="github-actions", help="Who triggered this.")
@click.option("--schema", default="", help="Schema name that was ingested.")
def cli(db: str, bump: str, issue: str, agent: str, schema: str) -> None:
    """Export registry snapshot, archive version, append provenance."""
    conn = get_connection(db)

    # Compute new registry version
    current = current_registry_version()
    new_ver  = next_registry_version(current, bump) if current != "0.0.0" else "1.0.0"
    click.echo(f"Registry version: {current} → {new_ver}")

    # Build snapshot
    snapshot = export_snapshot(conn, new_ver)
    nc = len(snapshot["classes"])
    ns = len(snapshot["sources"])

    # Write data/registry.json (latest)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    latest = DATA_DIR / "registry.json"
    latest.write_text(json.dumps(snapshot, indent=2))
    click.echo(f"Wrote {latest}  ({nc} classes, {ns} sources)")

    # Archive to data/versions/{ver}.json
    versions_dir = DATA_DIR / "versions"
    versions_dir.mkdir(exist_ok=True)
    archive = versions_dir / f"{new_ver}.json"
    shutil.copy(latest, archive)
    click.echo(f"Archived → {archive}")

    # Count changes vs previous version
    prev_path = DATA_DIR / "registry.json"
    classes_added = nc  # simplified — full diff would compare to previous snapshot

    # Append to provenance.json
    prov_entry = {
        "registry_version": new_ver,
        "previous_version": current,
        "timestamp":        now_iso(),
        "bump":             bump,
        "trigger":          "issue" if issue else "manual",
        "issue_number":     issue,
        "agent":            agent,
        "schema_ingested":  schema,
        "stats": {
            "classes_total":  nc,
            "sources_total":  ns,
        },
        "archive_path": f"data/versions/{new_ver}.json",
    }
    append_provenance(prov_entry)
    click.echo(f"Appended provenance entry for v{new_ver}")


if __name__ == "__main__":
    cli()
