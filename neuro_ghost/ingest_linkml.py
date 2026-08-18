"""
ingest_linkml.py — Load a LinkML schema into the NeuroGhost graph database
===========================================================================

WHY THIS FILE EXISTS
--------------------
When a researcher submits a schema (e.g. bbqs.yml, bids.yml), we need to
translate it from the human-readable LinkML YAML format into nodes and
relationships in our LadybugDB property graph.

This file is the bridge between the flat YAML file and the living graph.

WHAT LINKML IS
--------------
LinkML (Linked data Modeling Language) is a schema language used across
biomedical research. A LinkML file looks like this:

  classes:
    Person:
      description: A research investigator
      slots:
        - name
        - orcid

  slots:
    name:
      range: string
      description: Full name

We parse that YAML into our internal data structures, then write it into
LadybugDB as typed nodes connected by typed edges.

WHAT GETS CREATED IN THE GRAPH
-------------------------------
For every class → one RegistryClass node
For every slot  → one RegistryProperty node
For every slot declaring required/multivalued/pattern/min/max → one Rule
  node, linked to its property via APPLIES_TO_P (a plain property with none
  of these gets no Rule at all)
For every class→slot relationship → one HAS_PROPERTY edge
For every is_a relationship → one SUBCLASS_OF edge
For every schema file → one SchemaSource node + one SchemaVersionSnapshot
For every (entity, source) attestation → one ProvenanceEntry node, linked
  via HAS_PROVENANCE / HAS_PROVENANCE_P / HAS_PROVENANCE_RULE

CONTENT-ADDRESSED IDENTITY
---------------------------
A RegistryClass/RegistryProperty's hash_id is computed from its own semantic
content (name, description, range/units for properties; name, description,
properties/is_a/mixins for classes) — see schema_registry_utils.hashing.
Two properties from different schemas with identical content get the SAME
hash_id automatically; there is no separate content_id/SemanticIdentity
lookup layer anymore.

Identity is separate from provenance: ingesting the same content from a
second source doesn't create a second node, it adds a second ProvenanceEntry
to the existing one. There is no "version" or diff mechanism — a genuine
content change produces a different hash_id (a new entity), not an edit of
the old one.

USAGE
-----
  python ingest_linkml.py --file schemas/bbqs.yml
  python ingest_linkml.py                          # all schemas/*.yml
  python ingest_linkml.py --dry-run                # preview, no writes
  python ingest_linkml.py --wipe --file schemas/bbqs.yml  # remove this source's
                                                            # attestations first
"""

from __future__ import annotations
import re, sys
from pathlib import Path
from typing import Any

import click
from linkml_runtime.utils.schemaview import SchemaView

sys.path.insert(0, str(Path(__file__).parent.parent))
from schema_registry_utils import (
    RegistryClass, RegistryProperty, PermissibleValue, ValueSet, Rule,
    ProvenanceEntry, compute_hash_id_for,
)

from db import (
    get_connection, make_iri, make_uid, now_iso, REG,
    write_registry_entities, write_structural_edges,
)

DB_PATH = "./registry.lbug"

# ---------------------------------------------------------------------------
# Prefix resolution
# ---------------------------------------------------------------------------
# LinkML files use CURIEs like "schema:Person" instead of full IRIs like
# "https://schema.org/Person". We expand them to full IRIs using a prefix map.
#
# KNOWN_PREFIXES covers the most common ones. The schema file's own "prefixes:"
# block is merged on top, so schema-specific prefixes take precedence.

KNOWN_PREFIXES: dict[str, str] = {
    "schema":   "https://schema.org/",
    "xsd":      "http://www.w3.org/2001/XMLSchema#",
    "linkml":   "https://w3id.org/linkml/",
    "bbqs":     "https://brain-bbq-clone.lovable.app/schema#",
    "bids":     "https://bids-specification.readthedocs.io/en/stable/",
    "nwb":      "https://nwb-schema.readthedocs.io/en/latest/",
    "dandi":    "https://schema.dandiarchive.org/",
    "openminds":"https://openminds.ebrains.eu/",
    "aind":     "https://aind-data-schema.readthedocs.io/en/stable/",
}

# LinkML has its own built-in primitive types that map to XSD datatypes.
# We need this map because "range: string" in LinkML means xsd:string in RDF.
LINKML_PRIMITIVES: dict[str, str] = {
    "string":     "xsd:string",
    "integer":    "xsd:integer",
    "float":      "xsd:float",
    "double":     "xsd:double",
    "boolean":    "xsd:boolean",
    "date":       "xsd:date",
    "datetime":   "xsd:dateTime",
    "uri":        "xsd:anyURI",
    "uriorcurie": "xsd:anyURI",
    "curie":      "xsd:anyURI",
}


def resolve_prefix(curie: str, prefixes: dict[str, str]) -> str:
    """
    Expand a CURIE (Compact URI) to a full IRI.

    Example:
      resolve_prefix("schema:Person", {}) → "https://schema.org/Person"
      resolve_prefix("https://already.full/uri", {}) → "https://already.full/uri"
      resolve_prefix("unknownprefix:foo", {}) → "unknownprefix:foo"  (unchanged)

    Why: Storing full IRIs instead of CURIEs makes the graph self-contained.
    Two schemas using different prefixes for the same thing will resolve to
    the same IRI.
    """
    if not curie or ":" not in curie:
        return curie
    # If it already looks like a full URL, don't expand it
    if curie.startswith("http://") or curie.startswith("https://"):
        return curie
    prefix, local = curie.split(":", 1)
    all_prefixes = {**KNOWN_PREFIXES, **prefixes}
    if prefix in all_prefixes:
        return all_prefixes[prefix] + local
    return curie


# ---------------------------------------------------------------------------
# LinkML parser
# ---------------------------------------------------------------------------

def _slot_to_dict(slot, prefixes: dict[str, str]) -> dict:
    """
    Convert a SchemaView-induced SlotDefinition into our internal slot dict.

    "Induced" means inheritance (is_a), mixins, and schema-level default_range
    have already been resolved onto this slot by SchemaView — so a slot
    inherited from a mixin or parent class arrives here fully formed, exactly
    as if it had been declared directly.
    """
    slot_uri     = slot.slot_uri or ""
    resolved_iri = resolve_prefix(slot_uri, prefixes) if slot_uri else ""

    raw_range = slot.range if isinstance(slot.range, str) and slot.range else "string"
    if raw_range in LINKML_PRIMITIVES:
        value_range = LINKML_PRIMITIVES[raw_range]
    else:
        # It's a reference to another class/type/enum — store as a resolved IRI
        value_range = (resolve_prefix(raw_range, prefixes)
                      if ":" in raw_range else make_iri(raw_range))

    # Extract units from description if present (common in neuro schemas)
    desc = str(slot.description or "")
    units = ""
    if desc and "(units:" in desc.lower():
        m = re.search(r'\(units?:\s*([^)]+)\)', desc, re.IGNORECASE)
        if m:
            units = m.group(1).strip()

    return {
        "iri":         resolved_iri,
        "definition":  desc,
        "value_range": value_range,
        "units":       units,
        "multivalued": bool(slot.multivalued),
        "required":    bool(slot.required),
        "pattern":     slot.pattern or "",
        "minimum_value": slot.minimum_value,
        "maximum_value": slot.maximum_value,
    }


def parse_linkml(path: Path) -> dict[str, Any]:
    """
    Load a LinkML YAML file via SchemaView and return a clean, normalised dict.

    Using SchemaView instead of a hand-rolled YAML walk means classes get
    their real, induced slot set: slots inherited via is_a or mixins, slots
    declared inline as `attributes:`, and ranges defaulted from the schema's
    `default_range` all resolve exactly as LinkML defines them. A class that
    lists no slots of its own but has `is_a: Device` still gets Device's
    slots attached — the hand-rolled version silently dropped those.

    IRI resolution intentionally does NOT use SchemaView's own get_uri():
    imports (e.g. linkml:types) can declare their own "schema" prefix and,
    depending on import-merge order, shadow a schema's own `prefixes:`
    declaration — which would silently flip schema.org IRIs from
    https:// to http://, breaking identity matching against the
    https://schema.org/ IRIs seed.py uses. Resolving CURIEs ourselves from
    the schema's own top-level `prefixes:` block (schema's own declarations
    always win over KNOWN_PREFIXES) avoids that.

    Output (our internal format):
      {
        "meta": {"name": "bbqs", "version": "1.0.0", ...},
        "prefixes": {"schema": "https://schema.org/", ...},
        "classes": {
          "Person": {
            "iri": "https://schema.org/Person",
            "definition": "A person",
            "is_a": None,
            "is_abstract": False,
            "slots": ["name", "email"]
          }
        },
        "slots": {
          "name": {
            "iri": "https://schema.org/name",
            "definition": "",
            "value_range": "xsd:string",   ← primitive → XSD; class ref → IRI
            "multivalued": False,
            "required": False
          }
        }
      }
    """
    sv = SchemaView(str(path))

    prefixes = {k: v.prefix_reference for k, v in (sv.schema.prefixes or {}).items()}

    meta = {
        "id":          sv.schema.id or "",
        "name":        sv.schema.name or path.stem,
        "version":     str(sv.schema.version or "1.0.0"),
        "description": sv.schema.description or "",
    }

    classes: dict[str, dict] = {}
    slots: dict[str, dict] = {}

    for cls_name in sv.all_classes():
        cls_def = sv.get_class(cls_name)

        try:
            induced_slots = sv.class_induced_slots(cls_name)
        except (ValueError, KeyError) as exc:
            msg = str(exc)
            # Only tolerate "No such class" — that means is_a points outside
            # this schema (e.g. NWB's NWBContainer → Container).  A missing
            # slot is a genuine schema error; re-raise so the caller sees it.
            if "No such class" not in msg:
                raise
            induced_slots = list(cls_def.attributes.values())
            for sname in (cls_def.slots or []):
                try:
                    s = sv.get_slot(sname)
                    if s:
                        induced_slots.append(s)
                except Exception:
                    pass

        class_uri    = cls_def.class_uri or ""
        resolved_iri = resolve_prefix(class_uri, prefixes) if class_uri else ""

        # Strip is_a if the parent class isn't in this schema — build_registry_entities
        # already handles None gracefully; leaving a dangling name would be misleading.
        is_a = cls_def.is_a
        if is_a:
            try:
                sv.get_class(is_a)
            except (ValueError, KeyError):
                is_a = None

        classes[cls_name] = {
            "iri":         resolved_iri,
            "definition":  cls_def.description or "",
            "is_a":        is_a,
            "is_abstract": bool(cls_def.abstract),
            "slots":       [slot.name for slot in induced_slots],
        }

        for slot in induced_slots:
            if slot.name not in slots:
                slots[slot.name] = _slot_to_dict(slot, prefixes)

    enums: dict[str, dict] = {}
    for enum_name in sv.all_enums():
        enum_def = sv.get_enum(enum_name)
        enum_uri  = getattr(enum_def, "enum_uri", None) or ""
        resolved_iri = resolve_prefix(str(enum_uri), prefixes) if enum_uri else ""

        pv_dict: dict[str, dict] = {}
        for pv_text, pv_obj in (enum_def.permissible_values or {}).items():
            raw_meaning = getattr(pv_obj, "meaning", None)
            pv_dict[pv_text] = {
                "description": str(pv_obj.description or ""),
                "meaning": resolve_prefix(str(raw_meaning), prefixes) if raw_meaning else "",
            }

        enums[enum_name] = {
            "iri":        resolved_iri,
            "definition": str(enum_def.description or ""),
            "permissible_values": pv_dict,
        }

    return {
        "meta":     meta,
        "prefixes": prefixes,
        "classes":  classes,
        "slots":    slots,
        "enums":    enums,
    }


# ---------------------------------------------------------------------------
# Parsed dict → content-hashed RegistryClass / RegistryProperty
# ---------------------------------------------------------------------------

def _make_provenance(source_label: str, agent: str, issue: str = "",
                     registry_version: str = "",
                     activity: str = "ingestion") -> ProvenanceEntry:
    attributed_to = f"{agent} (issue #{issue})" if issue else agent
    return ProvenanceEntry(
        uid=make_uid(),
        source=source_label,
        registry_version=registry_version or None,
        generated_at=now_iso(),
        attributed_to=attributed_to,
        activity=activity,
        derived_from=[],
    )


def _has_constraints(slot: dict) -> bool:
    """Does this slot carry any usage constraint worth recording as a Rule?"""
    return bool(
        slot["required"] or slot["multivalued"] or slot["pattern"]
        or slot.get("minimum_value") is not None
        or slot.get("maximum_value") is not None
    )


def _describe_constraints(slot: dict) -> str:
    """Human-readable summary of a slot's usage constraints, for Rule.description."""
    parts = []
    if slot["required"]:
        parts.append("required")
    if slot["multivalued"]:
        parts.append("multivalued")
    if slot["pattern"]:
        parts.append(f"pattern: {slot['pattern']}")
    if slot.get("minimum_value") is not None:
        parts.append(f"min: {slot['minimum_value']}")
    if slot.get("maximum_value") is not None:
        parts.append(f"max: {slot['maximum_value']}")
    return "; ".join(parts)


def build_registry_entities(
    parsed: dict, source_label: str, agent: str, issue: str = "",
    registry_version: str = "",
) -> tuple[dict[str, RegistryProperty], dict[str, RegistryClass], dict[str, ValueSet], dict[str, Rule]]:
    """
    Convert parse_linkml()'s intermediate dict into content-hashed
    RegistryProperty/RegistryClass/Rule instances, keyed by their original
    slot/class name in the source schema.

    Properties are built first (classes reference them by hash_id in their
    own `properties` list, which itself feeds the class's hash — the same
    set of properties always produces the same class hash regardless of
    declaration order, since compute_hash_id() sorts reference lists).

    A class's `is_a` is resolved to its parent's hash_id recursively, so
    multi-level hierarchies resolve correctly regardless of declaration
    order. This always succeeds for any schema that reaches this point:
    parse_linkml() (via SchemaView) already requires every is_a target to
    resolve within the submitted schema's own import closure, so `classes`
    is guaranteed to contain it.

    A property that declares required/multivalued/pattern/min/max also gets
    a Rule referencing it (`applies_to` = the property's hash_id) — these
    usage constraints don't live on RegistryProperty itself (see
    RegistryProperty's docstring), and a plain property with none of them
    gets no Rule at all, so unconstrained properties don't accumulate noise.
    """
    slots   = parsed["slots"]
    classes = parsed["classes"]

    used_slots: set[str] = set()
    for cls in classes.values():
        used_slots.update(cls["slots"])

    properties: dict[str, RegistryProperty] = {}
    rules: dict[str, Rule] = {}
    for slot_name in used_slots:
        slot = slots.get(slot_name)
        if not slot:
            continue
        fields = dict(
            name=slot_name,
            description=slot["definition"] or "",
            range=slot["value_range"],
            units=slot.get("units") or None,
            slot_uri=slot["iri"] or None,
            skos_mappings=[],
        )
        prop = RegistryProperty(
            hash_id=compute_hash_id_for(RegistryProperty, fields),
            provenance=[_make_provenance(source_label, agent, issue, registry_version)],
            **fields,
        )
        properties[slot_name] = prop

        if _has_constraints(slot):
            rule_fields = dict(
                name=f"{slot_name}_rule",
                description=_describe_constraints(slot),
                applies_to=prop.hash_id,
                required=slot["required"],
                multivalued=slot["multivalued"],
                pattern=slot["pattern"] or None,
                minimum_value=slot.get("minimum_value"),
                maximum_value=slot.get("maximum_value"),
                # LinkML schemas don't carry executable Python — only manually
                # constructed Rules (not this ingestion path) ever set this.
                function_body=None,
                skos_mappings=[],
            )
            rule = Rule(
                hash_id=compute_hash_id_for(Rule, rule_fields),
                provenance=[_make_provenance(source_label, agent, issue, registry_version)],
                **rule_fields,
            )
            rules[slot_name] = rule

    registry_classes: dict[str, RegistryClass] = {}

    def resolve_class(cls_name: str) -> RegistryClass | None:
        if cls_name in registry_classes:
            return registry_classes[cls_name]
        cls = classes.get(cls_name)
        if cls is None:
            return None  # is_a points outside this schema — left unresolved

        parent_hash_id = None
        if cls["is_a"]:
            parent = resolve_class(cls["is_a"])
            parent_hash_id = parent.hash_id if parent else None

        prop_hash_ids = sorted({
            properties[s].hash_id for s in cls["slots"] if s in properties
        })
        fields = dict(
            name=cls_name,
            description=cls["definition"] or "",
            class_uri=cls["iri"] or None,
            abstract=cls["is_abstract"],
            is_a=parent_hash_id,
            properties=prop_hash_ids,
            relations=[],
            mixins=[],
            skos_mappings=[],
        )
        rc = RegistryClass(
            hash_id=compute_hash_id_for(RegistryClass, fields),
            provenance=[_make_provenance(source_label, agent, issue, registry_version)],
            **fields,
        )
        registry_classes[cls_name] = rc
        return rc

    for cls_name in classes:
        resolve_class(cls_name)

    # Build PermissibleValue + ValueSet instances from parsed enums.
    prov_factory = lambda: _make_provenance(source_label, agent, issue, registry_version)
    value_sets: dict[str, ValueSet] = {}

    for enum_name, enum_data in parsed.get("enums", {}).items():
        pv_hash_ids: list[str] = []
        for pv_text, pv_data in enum_data["permissible_values"].items():
            pv_fields = dict(
                name=pv_text,
                meaning=pv_data["meaning"] or None,
            )
            pv_hash_ids.append(compute_hash_id_for(PermissibleValue, pv_fields))

        vs_fields = dict(
            name=enum_name,
            description=enum_data["definition"] or "",
            permissible_values=sorted(pv_hash_ids),
            skos_mappings=[],
        )
        vs = ValueSet(
            hash_id=compute_hash_id_for(ValueSet, vs_fields),
            provenance=[prov_factory()],
            **vs_fields,
        )
        value_sets[enum_name] = vs

    return properties, registry_classes, value_sets, rules


# ---------------------------------------------------------------------------
# Graph writers
# ---------------------------------------------------------------------------
# entity_exists / create_entity_node / write_provenance / write_registry_entities
# / write_structural_edges all live in db.py — shared with seed.py, which
# writes the same two node types the same way.


# ---------------------------------------------------------------------------
# ValueSet / PermissibleValue graph writers
# ---------------------------------------------------------------------------

def _write_value_sets(conn, value_sets: dict[str, "ValueSet"],
                      enums: dict[str, dict]) -> int:
    """Write ValueSet and PermissibleValue nodes + edges. Returns edge count."""
    from db import entity_exists, create_entity_node, write_provenance, scalar_fields

    rels = 0
    for enum_name, vs in value_sets.items():
        is_new = not entity_exists(conn, "ValueSet", vs.hash_id)
        if is_new:
            create_entity_node(conn, "ValueSet", vs)
        for prov in vs.provenance:
            write_provenance(conn, "ValueSet", vs.hash_id, prov)

        # Write each PermissibleValue node and link it.
        for pv_text, pv_data in enums[enum_name]["permissible_values"].items():
            pv_fields = dict(name=pv_text, meaning=pv_data["meaning"] or None)
            pv_hash_id = compute_hash_id_for(PermissibleValue, pv_fields)

            pv_exists = conn.execute(
                "MATCH (p:PermissibleValue {hash_id: $h}) RETURN p.hash_id LIMIT 1",
                {"h": pv_hash_id},
            ).has_next()
            if not pv_exists:
                conn.execute("""
                    CREATE (:PermissibleValue {hash_id: $h, name: $n, meaning: $m})
                """, {"h": pv_hash_id, "n": pv_text, "m": pv_data["meaning"] or ""})

            edge_exists = conn.execute("""
                MATCH (vs:ValueSet {hash_id: $vs})-[:HAS_PERMISSIBLE_VALUE]->(pv:PermissibleValue {hash_id: $pv})
                RETURN vs.hash_id LIMIT 1
            """, {"vs": vs.hash_id, "pv": pv_hash_id}).has_next()
            if not edge_exists:
                conn.execute("""
                    MATCH (vs:ValueSet {hash_id: $vs}), (pv:PermissibleValue {hash_id: $pv})
                    CREATE (vs)-[:HAS_PERMISSIBLE_VALUE]->(pv)
                """, {"vs": vs.hash_id, "pv": pv_hash_id})
                rels += 1

    return rels


# ---------------------------------------------------------------------------
# Rule graph writer
# ---------------------------------------------------------------------------

def _write_rules(conn, rules: dict[str, "Rule"]) -> int:
    """Write Rule nodes + APPLIES_TO_P edges. Returns edge count."""
    from db import entity_exists, create_entity_node, write_provenance

    rels = 0
    for rule in rules.values():
        is_new = not entity_exists(conn, "Rule", rule.hash_id)
        if is_new:
            create_entity_node(conn, "Rule", rule)
        for prov in rule.provenance:
            write_provenance(conn, "Rule", rule.hash_id, prov)

        edge_exists = conn.execute("""
            MATCH (r:Rule {hash_id: $r})-[:APPLIES_TO_P]->(p:RegistryProperty {hash_id: $p})
            RETURN r.hash_id LIMIT 1
        """, {"r": rule.hash_id, "p": rule.applies_to}).has_next()
        if not edge_exists:
            conn.execute("""
                MATCH (r:Rule {hash_id: $r}), (p:RegistryProperty {hash_id: $p})
                CREATE (r)-[:APPLIES_TO_P]->(p)
            """, {"r": rule.hash_id, "p": rule.applies_to})
            rels += 1

    return rels


# ---------------------------------------------------------------------------
# SchemaSource / SchemaVersionSnapshot (unchanged in spirit from before)
# ---------------------------------------------------------------------------

def _ensure_schema_source(conn, source_label: str, version: str, registry_version: str) -> str:
    """One SchemaSource node per source label, reused across ingests."""
    r = conn.execute(
        "MATCH (s:SchemaSource {label: $label}) RETURN s.uid LIMIT 1",
        {"label": source_label},
    )
    if r.has_next():
        return r.get_next()[0]
    uid = make_uid()
    conn.execute("""
        CREATE (:SchemaSource {
            uid: $uid, source_iri: $source_iri,
            source_version: $source_version, created_at: $t,
            label: $label, mime_type: 'application/yaml',
            registry_version: $rv
        })
    """, {
        "uid": uid, "source_iri": f"{REG}source/{uid}", "source_version": version,
        "t": now_iso(), "label": source_label, "rv": registry_version,
    })
    return uid


def _prev_schema_version(conn, source_label: str) -> str | None:
    """Find the most recent SchemaVersionSnapshot for this schema, or None."""
    r = conn.execute("""
        MATCH (s:SchemaVersionSnapshot {schema_label: $src})
        RETURN s.source_version, s.created_at
        ORDER BY s.created_at DESC LIMIT 1
    """, {"src": source_label})
    return r.get_next()[0] if r.has_next() else None


def _bump_semver(ver: str, level: str) -> str:
    """
    Increment a semver string at the given level.

    Examples:
      _bump_semver("1.0.0", "patch") → "1.0.1"
      _bump_semver("1.0.0", "minor") → "1.1.0"
      _bump_semver("1.2.3", "major") → "2.0.0"
    """
    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 3:
        parts.append(0)
    if level == "major":
        parts[0] += 1; parts[1] = 0; parts[2] = 0
    elif level == "minor":
        parts[1] += 1; parts[2] = 0
    else:  # patch
        parts[2] += 1
    return ".".join(str(p) for p in parts)


# ---------------------------------------------------------------------------
# Main insertion logic
# ---------------------------------------------------------------------------

def insert_schema(conn, parsed: dict, source_label: str, agent: str = "anonymous",
                  issue: str = "", dry_run: bool = False,
                  registry_version: str = "", yml_path: str = "") -> dict:
    """
    Insert a parsed LinkML schema into the LadybugDB graph.

      1. Build content-hashed RegistryProperty/RegistryClass/Rule instances
      2. Write each one (skipped if its hash_id already exists) and attach
         this ingestion's ProvenanceEntry (skipped if this source already
         attested to it)
      3. Create HAS_PROPERTY, SUBCLASS_OF, and APPLIES_TO_P edges
      4. Record a SchemaVersionSnapshot — "minor" if any class/property was
         newly created, "patch" if only a new ProvenanceEntry was added
         (same content, newly attested by this source), unchanged otherwise

    Returns a stats dict.
    """
    meta = parsed["meta"]

    properties, registry_classes, value_sets, rules = build_registry_entities(
        parsed, source_label, agent, issue, registry_version,
    )

    stats = write_registry_entities(conn, properties, registry_classes, dry_run=dry_run)

    if dry_run:
        return stats

    _ensure_schema_source(conn, source_label, meta["version"], registry_version)
    stats["rels"] = write_structural_edges(conn, registry_classes)
    stats["rels"] += _write_value_sets(conn, value_sets, parsed.get("enums", {}))
    stats["rels"] += _write_rules(conn, rules)

    has_new_content = bool(stats["classes_new"] or stats["properties_new"])
    has_any_change   = has_new_content or bool(stats["provenance_added"])

    prev_ver = _prev_schema_version(conn, source_label)
    if prev_ver is None:
        schema_ver = meta.get("version") or "1.0.0"
    elif not has_any_change:
        stats["schema_version"] = prev_ver
        stats["schema_unchanged"] = True
        return stats
    else:
        level = "minor" if has_new_content else "patch"
        schema_ver = _bump_semver(prev_ver, level)

    changes_summary = (
        f"+{stats['classes_new']} classes, +{stats['properties_new']} props, "
        f"{stats['provenance_added']} provenance entries added"
    )

    snap_uid = make_uid()
    conn.execute("""
        CREATE (:SchemaVersionSnapshot {
            uid: $uid, source_version: $source_version, created_at: $created_at,
            schema_label: $sl, yml_path: $yp,
            class_count: $cc, property_count: $pc,
            changes_summary: $cs, registry_version: $rv
        })
    """, {
        "uid":            snap_uid,
        "source_version": schema_ver,
        "created_at":     now_iso(),
        "sl":  source_label,
        "yp":  yml_path,
        "cc":  len(registry_classes),
        "pc":  len(properties),
        "cs":  changes_summary,
        "rv":  registry_version,
    })
    stats["schema_version"] = schema_ver

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--file",    default=None,
              help="Path to a specific .yml file. Default: all schemas/*.yml")
@click.option("--db",      default=DB_PATH, show_default=True)
@click.option("--dry-run", is_flag=True,
              help="Parse and count without writing to DB.")
@click.option("--wipe",    is_flag=True,
              help="Remove this source's attestations before re-ingesting.")
@click.option("--registry-version", default="",
              help="Registry semver to stamp on created nodes.")
@click.option("--issue",   default="", help="GitHub issue number (for provenance).")
@click.option("--agent",   default="anonymous", help="Who submitted this schema.")
def cli(file, db, dry_run, wipe, registry_version, issue, agent) -> None:
    """
    Ingest one or more LinkML .yml schemas into the NeuroGhost graph.

    Examples:
      python ingest_linkml.py --file schemas/bbqs.yml
      python ingest_linkml.py --file schemas/bids.yml --dry-run
      python ingest_linkml.py --wipe --file schemas/nwb.yml
    """
    conn = get_connection(db)

    if file:
        files = [Path(file)]
    else:
        schemas_dir = Path("schemas")
        if not schemas_dir.exists():
            click.echo("No schemas/ directory. Use --file or create schemas/.")
            return
        files = sorted(schemas_dir.glob("*.yml"))
        if not files:
            click.echo("No .yml files in schemas/")
            return

    for path in files:
        click.echo(f"\nParsing {path} …")
        try:
            parsed = parse_linkml(path)
        except Exception as e:
            click.echo(f"  ERROR parsing {path}: {e}")
            continue

        source_label = parsed["meta"]["name"]
        click.echo(f"  Schema: {source_label} v{parsed['meta']['version']} "
                   f"({len(parsed['classes'])} classes, {len(parsed['slots'])} slots)")

        if wipe and not dry_run:
            click.echo(f"  Removing '{source_label}' attestations …")
            # Identity is shared across sources, so wiping a source means
            # detaching its ProvenanceEntry nodes, not deleting the
            # RegistryClass/RegistryProperty nodes themselves (another
            # source may still attest to the same content).
            conn.execute("""
                MATCH (:RegistryClass)-[:HAS_PROVENANCE]->(pe:ProvenanceEntry {source: $src})
                DETACH DELETE pe
            """, {"src": source_label})
            conn.execute("""
                MATCH (:RegistryProperty)-[:HAS_PROVENANCE_P]->(pe:ProvenanceEntry {source: $src})
                DETACH DELETE pe
            """, {"src": source_label})
            conn.execute("""
                MATCH (:Rule)-[:HAS_PROVENANCE_RULE]->(pe:ProvenanceEntry {source: $src})
                DETACH DELETE pe
            """, {"src": source_label})

        stats = insert_schema(
            conn, parsed, source_label, agent=agent, issue=issue,
            dry_run=dry_run,
            registry_version=registry_version,
            yml_path=str(path),
        )

        prefix = "[dry-run]" if dry_run else "Result:"
        click.echo(
            f"  {prefix} "
            f"+{stats.get('classes_new',0)} classes, "
            f"={stats.get('classes_existing',0)} existing | "
            f"+{stats.get('properties_new',0)} props, "
            f"={stats.get('properties_existing',0)} existing | "
            f"+{stats.get('provenance_added',0)} provenance entries"
        )
        if stats.get("schema_version"):
            click.echo(f"  Schema version: {stats['schema_version']}")
        if stats.get("schema_unchanged"):
            click.echo(f"  Schema unchanged — no snapshot created.")

        if not dry_run:
            nc = conn.execute("MATCH (n:RegistryClass) RETURN count(n)").get_next()[0]
            np = conn.execute("MATCH (n:RegistryProperty) RETURN count(n)").get_next()[0]
            npe = conn.execute("MATCH (n:ProvenanceEntry) RETURN count(n)").get_next()[0]
            click.echo(f"  Registry: {nc} classes, {np} properties, {npe} provenance entries")


if __name__ == "__main__":
    cli()
