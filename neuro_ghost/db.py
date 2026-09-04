"""
db.py — Shared DB setup for the SenseIn Schema Registry
--------------------------------------------------------
Single source of truth for:
  - LadybugDB connection
  - DDL:
      Registry entity node tables → generated from meta_model.yaml
        (via _build_registry_ddl). Edit that file and rebuild the DB to
        change node structure. SchemaSource and SchemaVersionSnapshot are
        first-class meta-model classes and come through the same path.
      Relationship tables → defined here (multivalued meta-model edges +
        alignment infrastructure).
  - Identity helpers (make_id, make_iri, now_iso)
  - Graph writers for content-addressed entities (scalar_fields,
    entity_exists, create_entity_node, write_provenance)

Import this in seed.py, ingest_linkml.py, align.py, export_json.py
so every script gets the same tables without duplicating DDL.
"""

from __future__ import annotations
import datetime
import hashlib as _hashlib
import uuid
from pathlib import Path

import ladybug as lb
import yaml as _yaml

# ---------------------------------------------------------------------------
# Registry namespace
# ---------------------------------------------------------------------------

REG = "https://registry.sensein.io/"

# ---------------------------------------------------------------------------
# Schema YAML — edit this file to change registry entity node structure
# ---------------------------------------------------------------------------

SCHEMA_YAML = Path(__file__).parent.parent / "meta_model.yaml"

# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()

def make_id() -> str:
    """Generate a random UUID string, for non-content-addressed entities
    (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping, ...)."""
    return str(uuid.uuid4())

def make_iri(object_id: str) -> str:
    return f"{REG}obj/{object_id}"

def bump_version(ver: str, bump: str = "patch") -> str:
    """
    Bump a semver string.
      bump="patch"  1.0.0 → 1.0.1
      bump="minor"  1.0.0 → 1.1.0
      bump="major"  1.0.0 → 2.0.0
    """
    major, minor, patch = (int(x) for x in ver.split("."))
    if bump == "major":
        return f"{major+1}.0.0"
    elif bump == "minor":
        return f"{major}.{minor+1}.0"
    else:
        return f"{major}.{minor}.{patch+1}"

# ---------------------------------------------------------------------------
# Graph writers for content-addressed entities (RegistryClass, RegistryProperty)
# ---------------------------------------------------------------------------
# Shared by every script that writes these node types (ingest_linkml.py,
# seed.py, ...): write the node only if its id doesn't already exist,
# then attach a ProvenanceEntry unless this exact source already attested to
# it. This is how "identity is separate from provenance" plays out on disk.
#
# Duck-typed on purpose (entity just needs .model_dump(); prov just needs
# .id/.had_primary_source/.source_version/.generated_at_time/
# .was_attributed_to/.was_generated_by/.was_derived_from) so this module
# doesn't need to import schema_registry_utils.

LIST_FIELDS = {
    "provenance", "skos_mappings", "properties", "class_mixins", "permissible_values",
    "registry_classes", "registry_properties", "registry_rules", "registry_value_sets",
    "applies_to", "referenced_entities",
}
HAS_PROVENANCE_REL = {
    "RegistryClass":    "HAS_PROVENANCE",
    "RegistryProperty": "HAS_PROVENANCE_P",
    "RegistryRule":      "HAS_PROVENANCE_R",
    "RegistryValueSet":  "HAS_PROVENANCE_VS",
    "PermissibleValue":  "HAS_PROVENANCE_PV",
}

# Inline class fields (db_inline in the meta-model): each one's sub-fields
# become their own columns on the *parent's* node table (see
# _build_registry_ddl()), never a "unit"-named column of their own. Kept
# explicit here, matching LIST_FIELDS/HAS_PROVENANCE_REL's style, rather than
# introspecting meta_model.yaml at write time.
# No inline classes remain in the meta-model (UnitOfMeasure was removed when
# unit moved to a UNIT RegistryRule). Kept as an extension point: a db_inline
# class would map its field name here to the sub-fields it flattens into the
# parent's node table.
INLINE_FIELDS: dict[str, tuple[str, ...]] = {}


def scalar_fields(entity) -> dict:
    """
    An entity's own node-table columns — excludes list/edge-backed fields.

    A plain list-of-scalars field (e.g. aliases) is passed through as a real
    Python list, bound against a native list column (e.g. STRING[]) — see
    _build_registry_ddl(). Do NOT JSON-encode it into a STRING column: a
    bound string that looks like a Cypher list literal gets silently
    reparsed and corrupted by the DB engine.

    An inline-class field (e.g. unit) is flattened into its sub-fields —
    always, even when the whole thing is None — since the DDL never creates
    a column named after the field itself, only after its sub-fields.
    """
    fields = {k: v for k, v in entity.model_dump().items() if k not in LIST_FIELDS}
    flattened: dict = {}
    for k, v in fields.items():
        if k in INLINE_FIELDS:
            sub = v or {}
            flattened.update({name: sub.get(name) for name in INLINE_FIELDS[k]})
        else:
            flattened[k] = v
    return flattened


def entity_exists(conn, label: str, node_id: str) -> bool:
    return conn.execute(
        f"MATCH (n:{label} {{id: $node_id}}) RETURN n.id LIMIT 1",
        {"node_id": node_id},
    ).has_next()


def find_id_by_sha256(conn, label: str, sha256_hash: str) -> str | None:
    """Return the existing entity's id if any row of this label already has
    the given sha256_hash — used by build_registry_entities to reuse an id
    for content that already appears in the graph. None if unseen."""
    r = conn.execute(
        f"MATCH (n:{label} {{sha256_hash: $sha}}) RETURN n.id LIMIT 1",
        {"sha": sha256_hash},
    )
    return r.get_next()[0] if r.has_next() else None


def create_entity_node(conn, label: str, entity) -> None:
    fields = scalar_fields(entity)
    prop_str = ", ".join(f"{k}: ${k}" for k in fields)
    conn.execute(f"CREATE (:{label} {{{prop_str}}})", fields)


def write_provenance(conn, label: str, node_id: str, prov) -> bool:
    """
    Attach a ProvenanceEntry to an entity, unless this exact source has
    already attested to it. Returns True if a new ProvenanceEntry was added.

    had_primary_source is a real Entity->Entity link (prov:hadPrimarySource)
    to the attesting SchemaSource, not a denormalized label — so this also
    creates the HAD_PRIMARY_SOURCE edge alongside the ProvenanceEntry node.
    prov.had_primary_source must already be a SchemaSource id (the caller
    ensures that source exists before building any ProvenanceEntry).
    """
    rel = HAS_PROVENANCE_REL[label]
    already = conn.execute(f"""
        MATCH (n:{label} {{id: $node_id}})-[:{rel}]->(pe:ProvenanceEntry {{had_primary_source: $had_primary_source}})
        RETURN pe.id LIMIT 1
    """, {"node_id": node_id, "had_primary_source": prov.had_primary_source}).has_next()
    if already:
        return False

    pe_id = prov.id or make_id()
    conn.execute("""
        CREATE (:ProvenanceEntry {
            id: $id, attests_to: $attests_to,
            had_primary_source: $had_primary_source, source_version: $source_version,
            registry_version: $registry_version,
            generated_at_time: $generated_at_time, was_attributed_to: $was_attributed_to,
            was_generated_by: $was_generated_by, was_derived_from: $was_derived_from
        })
    """, {
        "id":                  pe_id,
        "attests_to":         prov.attests_to,
        "had_primary_source": prov.had_primary_source,
        "source_version":     prov.source_version,
        "registry_version":   prov.registry_version,
        "generated_at_time":  prov.generated_at_time.isoformat(),
        "was_attributed_to":  prov.was_attributed_to,
        "was_generated_by":   prov.was_generated_by,
        "was_derived_from":   prov.was_derived_from,
    })
    conn.execute(f"""
        MATCH (n:{label} {{id: $node_id}}), (pe:ProvenanceEntry {{id: $pe_id}})
        CREATE (n)-[:{rel}]->(pe)
    """, {"node_id": node_id, "pe_id": pe_id})
    conn.execute("""
        MATCH (pe:ProvenanceEntry {id: $id}), (ss:SchemaSource {id: $ss_id})
        CREATE (pe)-[:HAD_PRIMARY_SOURCE]->(ss)
    """, {"id": pe_id, "ss_id": prov.had_primary_source})
    return True


def ensure_schema_source(conn, source_label: str, version: str, registry_version: str,
                         dry_run: bool = False, metadata: dict | None = None) -> str:
    """
    One SchemaSource node per source label, reused across ingests. Shared by
    ingest_linkml.py and seed.py, same as the other entity/provenance writers.

    Must run before any ProvenanceEntry is built, since
    ProvenanceEntry.had_primary_source is a real FK to it — including in
    --dry-run, which must stay read-only. In dry-run, an as-yet-unseen
    source gets a throwaway placeholder id instead of a real CREATE;
    nothing downstream persists it anyway.
    """
    r = conn.execute(
        "MATCH (s:SchemaSource {label: $label}) RETURN s.id LIMIT 1",
        {"label": source_label},
    )
    if r.has_next():
        return r.get_next()[0]
    if dry_run:
        return f"dry-run-placeholder:{source_label}"
    node_id = make_id()
    # Descriptive metadata supplied by the caller, keyed by SchemaSource slot
    # name: `title`/`source_id` are propagated from the schema's own title:/id:,
    # and any of publisher/contact/homepage/source_iri/source_version/mime_type
    # may come from its <stem>_source.yaml sidecar. All optional. `source_id` is
    # the source's declared id:; `source_iri` is a canonical registry IRI
    # (synthetic unless the sidecar overrides it).
    md = metadata or {}
    conn.execute("""
        CREATE (:SchemaSource {
            id: $id, label: $label, created_at: $t, registry_version: $rv,
            source_id: $source_id, source_iri: $source_iri,
            source_version: $source_version, mime_type: $mime_type,
            title: $title, publisher: $publisher, contact: $contact,
            homepage: $homepage
        })
    """, {
        "id": node_id, "label": source_label, "t": now_iso(), "rv": registry_version,
        "source_id": md.get("source_id", ""),
        "source_iri": md.get("source_iri") or f"{REG}source/{node_id}",
        "source_version": md.get("source_version") or version,
        "mime_type": md.get("mime_type") or "application/yaml",
        "title": md.get("title", ""), "publisher": md.get("publisher", ""),
        "contact": md.get("contact", ""), "homepage": md.get("homepage", ""),
    })
    return node_id


def write_registry_entities(conn, properties: dict, registry_classes: dict,
                             rules: dict, provenance_entries: dict,
                             dry_run: bool = False) -> dict:
    """
    Write (or reuse) each property/class/rule node by id, then attach this
    ingestion's ProvenanceEntry to every one of them. Existing nodes are
    never overwritten — a matching id means dedup already resolved this
    to identical content (see build_registry_entities' sha256_hash lookup),
    so there is nothing to update; only a new ProvenanceEntry may need
    attaching.

    `properties`/`registry_classes`/`rules` are name -> entity dicts, and
    each entity's `.provenance` is a list of ProvenanceEntry.id references
    (not embedded objects — the meta_model stores provenance by id, so the
    caller passes the ProvenanceEntry dict alongside for lookup).
    """
    stats = {
        "properties_new": 0, "properties_existing": 0,
        "classes_new":    0, "classes_existing":    0,
        "rules_new":      0, "rules_existing":       0,
        "provenance_added": 0,
    }

    for prop in properties.values():
        is_new = not entity_exists(conn, "RegistryProperty", prop.id)
        if is_new and not dry_run:
            create_entity_node(conn, "RegistryProperty", prop)
        stats["properties_new" if is_new else "properties_existing"] += 1
        if not dry_run:
            for prov_id in prop.provenance:
                if write_provenance(conn, "RegistryProperty", prop.id, provenance_entries[prov_id]):
                    stats["provenance_added"] += 1

    for rc in registry_classes.values():
        is_new = not entity_exists(conn, "RegistryClass", rc.id)
        if is_new and not dry_run:
            create_entity_node(conn, "RegistryClass", rc)
        stats["classes_new" if is_new else "classes_existing"] += 1
        if not dry_run:
            for prov_id in rc.provenance:
                if write_provenance(conn, "RegistryClass", rc.id, provenance_entries[prov_id]):
                    stats["provenance_added"] += 1

    for rule in rules.values():
        is_new = not entity_exists(conn, "RegistryRule", rule.id)
        if is_new and not dry_run:
            create_entity_node(conn, "RegistryRule", rule)
        stats["rules_new" if is_new else "rules_existing"] += 1
        if not dry_run:
            for prov_id in rule.provenance:
                if write_provenance(conn, "RegistryRule", rule.id, provenance_entries[prov_id]):
                    stats["provenance_added"] += 1

    return stats


def write_structural_edges(conn, registry_classes: dict) -> int:
    """
    HAS_PROPERTY (from each class's own `properties`) + SUBCLASS_OF (from
    `is_a`, which is already resolved to an id or None by the caller) +
    MIXIN (from `class_mixins`, same resolved-id shape).
    """
    rels = 0

    for rc in registry_classes.values():
        for prop_id in rc.properties:
            already = conn.execute("""
                MATCH (c:RegistryClass {id: $c})-[:HAS_PROPERTY]->(p:RegistryProperty {id: $p})
                RETURN c.id LIMIT 1
            """, {"c": rc.id, "p": prop_id}).has_next()
            if not already:
                conn.execute("""
                    MATCH (c:RegistryClass {id: $c}), (p:RegistryProperty {id: $p})
                    CREATE (c)-[:HAS_PROPERTY]->(p)
                """, {"c": rc.id, "p": prop_id})
                rels += 1

    for rc in registry_classes.values():
        parent_id = rc.parent_class
        if not parent_id:
            continue

        already = conn.execute("""
            MATCH (c:RegistryClass {id: $c})-[:SUBCLASS_OF]->(p:RegistryClass {id: $p})
            RETURN c.id LIMIT 1
        """, {"c": rc.id, "p": parent_id}).has_next()
        if not already:
            conn.execute("""
                MATCH (c:RegistryClass {id: $c}), (p:RegistryClass {id: $p})
                CREATE (c)-[:SUBCLASS_OF]->(p)
            """, {"c": rc.id, "p": parent_id})
            rels += 1

    for rc in registry_classes.values():
        for mixin_id in rc.class_mixins:
            already = conn.execute("""
                MATCH (c:RegistryClass {id: $c})-[:MIXIN]->(m:RegistryClass {id: $m})
                RETURN c.id LIMIT 1
            """, {"c": rc.id, "m": mixin_id}).has_next()
            if not already:
                conn.execute("""
                    MATCH (c:RegistryClass {id: $c}), (m:RegistryClass {id: $m})
                    CREATE (c)-[:MIXIN]->(m)
                """, {"c": rc.id, "m": mixin_id})
                rels += 1

    return rels


def write_rule_edges(conn, rules: dict, registry_classes: dict, properties: dict) -> int:
    """
    APPLIES_TO/APPLIES_TO_P (from each rule's `applies_to`, split by
    target-node-type since a Kùzu REL table has a fixed FROM/TO pair) and
    USED_IN_CLASS (from `used_in_class`, if set).
    """
    class_ids = {rc.id for rc in registry_classes.values()}
    property_ids = {p.id for p in properties.values()}
    rels = 0

    for rule in rules.values():
        for target_id in rule.applies_to:
            if target_id in class_ids:
                rel, label = "APPLIES_TO", "RegistryClass"
            elif target_id in property_ids:
                rel, label = "APPLIES_TO_P", "RegistryProperty"
            else:
                continue  # target not in this ingestion's batch

            already = conn.execute(f"""
                MATCH (r:RegistryRule {{id: $r}})-[:{rel}]->(t:{label} {{id: $t}})
                RETURN r.id LIMIT 1
            """, {"r": rule.id, "t": target_id}).has_next()
            if not already:
                conn.execute(f"""
                    MATCH (r:RegistryRule {{id: $r}}), (t:{label} {{id: $t}})
                    CREATE (r)-[:{rel}]->(t)
                """, {"r": rule.id, "t": target_id})
                rels += 1

        if rule.used_in_class:
            already = conn.execute("""
                MATCH (r:RegistryRule {id: $r})-[:USED_IN_CLASS]->(c:RegistryClass {id: $c})
                RETURN r.id LIMIT 1
            """, {"r": rule.id, "c": rule.used_in_class}).has_next()
            if not already:
                conn.execute("""
                    MATCH (r:RegistryRule {id: $r}), (c:RegistryClass {id: $c})
                    CREATE (r)-[:USED_IN_CLASS]->(c)
                """, {"r": rule.id, "c": rule.used_in_class})
                rels += 1

    return rels


def skos_relation(distance: float, is_subclass: bool = False) -> str:
    """
    Map a numeric distance to a SKOS mapping relation.
      0.0        → skos:exactMatch
      ≤ 0.1      → skos:closeMatch
      ≤ 0.4      → skos:broadMatch / skos:narrowMatch
      ≤ 0.7      → skos:relatedMatch
      > 0.7      → (no relation — don't write the edge)
    """
    if distance == 0.0:
        return "skos:exactMatch"
    if distance <= 0.1:
        return "skos:closeMatch"
    if distance <= 0.4:
        return "skos:narrowMatch" if is_subclass else "skos:broadMatch"
    if distance <= 0.7:
        return "skos:relatedMatch"
    return ""


# ---------------------------------------------------------------------------
# YAML → DDL generator
# ---------------------------------------------------------------------------

_LINKML_TYPE_MAP: dict[str, str] = {
    "string":     "STRING",
    "str":        "STRING",
    "datetime":   "STRING",
    "boolean":    "BOOLEAN",
    "bool":       "BOOLEAN",
    "uriorcurie": "STRING",
    "uri":        "STRING",
    "integer":    "INT64",
    "int":        "INT64",
    "double":     "DOUBLE",
    "float":      "FLOAT",
}


def _resolve_slots(cls_name: str, classes: dict, all_slots: dict) -> dict:
    """Collect effective slots for a class including inherited ones (own wins)."""
    cls_def = classes.get(cls_name, {})
    parent = cls_def.get("is_a")
    parent_slots = _resolve_slots(parent, classes, all_slots) if parent else {}
    own_slots = {s: all_slots.get(s, {}) for s in cls_def.get("slots", [])}
    return {**parent_slots, **own_slots}


def _build_registry_ddl(yaml_path: str | Path = SCHEMA_YAML) -> list[str]:
    """
    Read the meta-model YAML and return CREATE NODE TABLE statements for all
    non-abstract, non-inline classes.

    Column rules per slot:
    - db_inline class ref → flatten its slots inline.
    - Multivalued class ref (e.g. provenance) → REL table (handled in _REL_DDL below; skipped here).
    - Non-multivalued class ref → STRING column (id FK).
    - Multivalued scalar (e.g. aliases) → native list column, e.g. STRING[].
      NOT a JSON-encoded STRING: a bound parameter string that looks like a
      Cypher list literal (starts with "[") gets silently reparsed and
      corrupted by the DB engine, so multivalued scalars must go through
      as real Python lists bound against a real list column.
    - Plain scalar → mapped type; identifier slots get PRIMARY KEY.
    """
    schema = _yaml.safe_load(Path(yaml_path).read_text())
    classes: dict = schema.get("classes", {})
    all_slots: dict = schema.get("slots", {})

    inline_classes = {
        name
        for name, cls_def in classes.items()
        if cls_def.get("annotations", {}).get("db_inline")
    }

    stmts: list[str] = []

    for cls_name, cls_def in classes.items():
        if cls_def.get("abstract") or cls_name in inline_classes:
            continue

        slots = _resolve_slots(cls_name, classes, all_slots)
        columns: list[str] = []

        for slot_name, slot_def in slots.items():
            range_    = slot_def.get("range", "string")
            multi     = slot_def.get("multivalued", False)
            is_id     = slot_def.get("identifier", False)

            if range_ in inline_classes:
                if not multi:
                    for sub_name, sub_def in _resolve_slots(
                        range_, classes, all_slots
                    ).items():
                        sub_range = sub_def.get("range", "string")
                        sub_multi = sub_def.get("multivalued", False)
                        if sub_range not in classes:
                            sub_db_type = _LINKML_TYPE_MAP.get(sub_range, "STRING")
                            if sub_multi:
                                columns.append(f"    {sub_name:<24} {sub_db_type}[]")
                            else:
                                columns.append(f"    {sub_name:<24} {sub_db_type}")
                # multivalued inline → not supported; skip

            elif range_ in classes:
                if not multi:
                    # Non-multivalued class ref → STRING FK (id)
                    columns.append(f"    {slot_name:<24} STRING")
                # multivalued → REL table, not a column

            else:
                # Scalar
                db_type = _LINKML_TYPE_MAP.get(range_, "STRING")
                if multi:
                    columns.append(f"    {slot_name:<24} {db_type}[]")
                elif is_id:
                    columns.append(
                        f"    {slot_name:<24} {db_type} PRIMARY KEY"
                    )
                else:
                    columns.append(f"    {slot_name:<24} {db_type}")

        if columns:
            col_str = ",\n".join(columns)
            stmts.append(
                f"CREATE NODE TABLE IF NOT EXISTS {cls_name} (\n{col_str}\n)"
            )

    return stmts


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

# Registry entity node tables — generated from meta_model.yaml.
# To add/remove columns: edit the YAML and rebuild the database.
_REGISTRY_NODE_DDL: list[str] = _build_registry_ddl()

# Infrastructure node tables — not part of the meta-model; defined here.
# All node tables are generated from meta_model.yaml by _build_registry_ddl().
# SchemaActivity + SemanticIdentity used to live here as hand-written
# infrastructure tables; both were superseded by content-hash identity +
# ProvenanceEntry (no code ever wrote to either) and have been removed.

# Relationship tables — multivalued meta-model edges + alignment infrastructure.
_REL_DDL: list[str] = [
    # --- Meta-model multivalued edges ---
    "CREATE REL TABLE IF NOT EXISTS HAS_PROPERTY       (FROM RegistryClass    TO RegistryProperty)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING   (FROM RegistryClass    TO Mapping)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING_P (FROM RegistryProperty TO Mapping)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE     (FROM RegistryClass    TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_P   (FROM RegistryProperty TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAD_PRIMARY_SOURCE (FROM ProvenanceEntry  TO SchemaSource)",
    "CREATE REL TABLE IF NOT EXISTS MIXIN              (FROM RegistryClass    TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS SUBCLASS_OF        (FROM RegistryClass    TO RegistryClass)",

    # --- Version chains (carry diff data between consecutive versions) ---
    """CREATE REL TABLE IF NOT EXISTS PRIOR_VERSION (
        FROM RegistryClass TO RegistryClass,
        diff_summary        STRING,
        changed_fields      STRING,
        added_properties    STRING,
        removed_properties  STRING,
        definition_from     STRING,
        definition_to       STRING,
        registry_version    STRING,
        created_at          STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS PRIOR_VERSION_P (
        FROM RegistryProperty TO RegistryProperty,
        diff_summary        STRING,
        changed_fields      STRING,
        definition_from     STRING,
        definition_to       STRING,
        datatype_from       STRING,
        datatype_to         STRING,
        registry_version    STRING,
        created_at          STRING
    )""",
    """CREATE REL TABLE IF NOT EXISTS PRIOR_VERSION_R (
        FROM RegistryRule TO RegistryRule,
        diff_summary        STRING,
        changed_fields      STRING,
        registry_version    STRING,
        created_at          STRING
    )""",

    # --- RegistryValueSet / PermissibleValue ---
    "CREATE REL TABLE IF NOT EXISTS HAS_PERMISSIBLE_VALUE (FROM RegistryValueSet TO PermissibleValue)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_VS     (FROM RegistryValueSet TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_PV     (FROM PermissibleValue TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING_PV   (FROM PermissibleValue TO Mapping)",

    # --- RegistryRule ---
    # RegistryRule.applies_to has range RegistryEntity, so ingestion may target either
    # a class (a class-scoped or cross-field rule) or a property (a plain
    # property-level constraint). Two REL tables so a query can filter by
    # target kind without matching both.
    # RegistryRule inherits provenance and skos_mappings from RegistryEntity — the
    # HAS_PROVENANCE_R / HAS_SKOS_MAPPING_R edges are the same pattern as the
    # RegistryClass / RegistryProperty / RegistryValueSet / PermissibleValue variants.
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO         (FROM RegistryRule TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO_P       (FROM RegistryRule TO RegistryProperty)",
    "CREATE REL TABLE IF NOT EXISTS USED_IN_CLASS      (FROM RegistryRule TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_R   (FROM RegistryRule TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING_R (FROM RegistryRule TO Mapping)",
    # referenced_entities is also range RegistryEntity, multivalued — same
    # two-table split as applies_to, for the same reason.
    "CREATE REL TABLE IF NOT EXISTS REFERENCED_ENTITIES   (FROM RegistryRule TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCED_ENTITIES_P (FROM RegistryRule TO RegistryProperty)",

    # --- RegistrySchema ---
    # registry_classes/registry_properties/registry_rules/registry_value_sets
    # are all multivalued class-range slots, so each gets its own REL table
    # (same reason RegistryRule.applies_to needed two above: one FROM/TO
    # pair per table).
    "CREATE REL TABLE IF NOT EXISTS HAS_MEMBER_CLASS    (FROM RegistrySchema TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS HAS_MEMBER_PROPERTY (FROM RegistrySchema TO RegistryProperty)",
    "CREATE REL TABLE IF NOT EXISTS HAS_MEMBER_RULE     (FROM RegistrySchema TO RegistryRule)",
    "CREATE REL TABLE IF NOT EXISTS HAS_MEMBER_VALUESET (FROM RegistrySchema TO RegistryValueSet)",

    # --- Alignment ---
    """CREATE REL TABLE IF NOT EXISTS ALIGNED_TO (
        FROM RegistryClass TO RegistryClass,
        distance         DOUBLE,
        method           STRING,
        skos_relation    STRING,
        score_iri        DOUBLE,
        score_name       DOUBLE,
        score_desc       DOUBLE,
        score_slot       DOUBLE,
        registry_version STRING
    )""",
]

DDL = _REGISTRY_NODE_DDL + _REL_DDL


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def _migrate_aligned_to(conn: lb.Connection) -> None:
    """Drop and recreate ALIGNED_TO if it lacks current columns."""
    try:
        conn.execute("""
            MATCH (a:RegistryClass), (b:RegistryClass)
            WHERE a.id <> b.id
            WITH a, b LIMIT 1
            CREATE (a)-[:ALIGNED_TO {
                distance: 0.0, method: '__probe__',
                skos_relation: '',
                score_iri: 0.0, score_name: 0.0,
                score_desc: 0.0, score_slot: 0.0,
                registry_version: ''
            }]->(b)
        """)
        conn.execute(
            "MATCH ()-[r:ALIGNED_TO {method: '__probe__'}]->() DELETE r"
        )
    except Exception:
        try:
            conn.execute("DROP TABLE ALIGNED_TO")
        except Exception:
            pass
        conn.execute("""
            CREATE REL TABLE ALIGNED_TO (
                FROM RegistryClass TO RegistryClass,
                distance         DOUBLE,
                method           STRING,
                skos_relation    STRING,
                score_iri        DOUBLE,
                score_name       DOUBLE,
                score_desc       DOUBLE,
                score_slot       DOUBLE,
                registry_version STRING
            )
        """)


def _migrate_prior_version(conn: lb.Connection) -> None:
    """Drop and recreate PRIOR_VERSION tables if they lack diff fields."""
    try:
        conn.execute("""
            MATCH (a:RegistryClass), (b:RegistryClass)
            WHERE a.id <> b.id
            WITH a, b LIMIT 1
            CREATE (a)-[:PRIOR_VERSION {
                diff_summary: '__probe__', changed_fields: '',
                added_properties: '', removed_properties: '',
                definition_from: '', definition_to: '',
                registry_version: '', created_at: ''
            }]->(b)
        """)
        conn.execute(
            "MATCH ()-[r:PRIOR_VERSION {diff_summary: '__probe__'}]->() DELETE r"
        )
    except Exception:
        try:
            conn.execute("DROP TABLE PRIOR_VERSION")
        except Exception:
            pass
        conn.execute("""
            CREATE REL TABLE PRIOR_VERSION (
                FROM RegistryClass TO RegistryClass,
                diff_summary        STRING,
                changed_fields      STRING,
                added_properties    STRING,
                removed_properties  STRING,
                definition_from     STRING,
                definition_to       STRING,
                registry_version    STRING,
                created_at          STRING
            )
        """)

    try:
        conn.execute("""
            MATCH (a:RegistryProperty), (b:RegistryProperty)
            WHERE a.id <> b.id
            WITH a, b LIMIT 1
            CREATE (a)-[:PRIOR_VERSION_P {
                diff_summary: '__probe__', changed_fields: '',
                definition_from: '', definition_to: '',
                datatype_from: '', datatype_to: '',
                registry_version: '', created_at: ''
            }]->(b)
        """)
        conn.execute(
            "MATCH ()-[r:PRIOR_VERSION_P {diff_summary: '__probe__'}]->() DELETE r"
        )
    except Exception:
        try:
            conn.execute("DROP TABLE PRIOR_VERSION_P")
        except Exception:
            pass
        conn.execute("""
            CREATE REL TABLE PRIOR_VERSION_P (
                FROM RegistryProperty TO RegistryProperty,
                diff_summary     STRING,
                changed_fields   STRING,
                definition_from  STRING,
                definition_to    STRING,
                datatype_from    STRING,
                datatype_to      STRING,
                registry_version STRING,
                created_at       STRING
            )
        """)


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def get_connection(db_path: str = "./registry.lbug") -> lb.Connection:
    """Open (or create) a LadybugDB database and ensure all tables exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db   = lb.Database(db_path)
    conn = lb.Connection(db)
    for stmt in DDL:
        conn.execute(stmt)
    _migrate_aligned_to(conn)
    _migrate_prior_version(conn)
    return conn


# ---------------------------------------------------------------------------
# Registry version helpers
# ---------------------------------------------------------------------------

PROVENANCE_PATH = "data/provenance.json"

def current_registry_version(provenance_path: str = PROVENANCE_PATH) -> str:
    """Read current registry version from provenance.json. Default 0.0.0."""
    import json
    p = Path(provenance_path)
    if not p.exists():
        return "0.0.0"
    entries = json.loads(p.read_text())
    if not entries:
        return "0.0.0"
    return entries[-1]["registry_version"]

def next_registry_version(current: str, bump: str = "minor") -> str:
    return bump_version(current, bump)

def append_provenance(entry: dict,
                      provenance_path: str = PROVENANCE_PATH) -> None:
    """Append a provenance entry to data/provenance.json."""
    import json
    p = Path(provenance_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(p.read_text()) if p.exists() else []
    entries.append(entry)
    p.write_text(json.dumps(entries, indent=2))
