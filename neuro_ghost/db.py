"""
db.py — Shared DB setup for the SenseIn Schema Registry
--------------------------------------------------------
Single source of truth for:
  - LadybugDB connection
  - DDL:
      Registry entity node tables → generated from schemas/meta_model.yaml.
        Edit that file and rebuild the DB to change node structure.
      Infrastructure node tables (SchemaSource, SchemaVersionSnapshot,
        SchemaActivity, SemanticIdentity) → defined here; rarely change.
        SemanticIdentity + HAS_IDENTITY/HAS_IDENTITY_P + PRIOR_VERSION* are
        unused now (superseded by content-hash identity + ProvenanceEntry)
        but not yet removed — a separate cleanup pass, not touched here.
      Relationship tables → defined here.
  - Identity helpers (make_uid, make_iri, now_iso)
  - Graph writers for content-addressed entities (scalar_fields,
    entity_exists, create_entity_node, write_provenance)

Import this in seed.py, ingest_linkml.py, align.py, export_json.py
so every script gets the same tables without duplicating DDL.
"""

from __future__ import annotations
import datetime
import hashlib as _hashlib
import json as _json
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

SCHEMA_YAML = Path(__file__).parent.parent / "schemas" / "meta_model.yaml"

# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()

def make_uid() -> str:
    """Generate a random UUID string, for non-content-addressed entities
    (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, ...)."""
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
# seed.py, ...): write the node only if its hash_id doesn't already exist,
# then attach a ProvenanceEntry unless this exact source already attested to
# it. This is how "identity is separate from provenance" plays out on disk.
#
# Duck-typed on purpose (entity just needs .model_dump(); prov just needs
# .uid/.source/.source_description/.generated_at/.attributed_to/.activity/
# .derived_from) so this module doesn't need to import schema_registry_utils.

LIST_FIELDS = {"provenance", "skos_mappings", "properties", "relations", "mixins"}
HAS_PROVENANCE_REL = {"RegistryClass": "HAS_PROVENANCE", "RegistryProperty": "HAS_PROVENANCE_P"}


def scalar_fields(entity) -> dict:
    """An entity's own node-table columns — excludes list/edge-backed fields."""
    return {k: v for k, v in entity.model_dump().items() if k not in LIST_FIELDS}


def entity_exists(conn, label: str, hash_id: str) -> bool:
    return conn.execute(
        f"MATCH (n:{label} {{hash_id: $hash_id}}) RETURN n.hash_id LIMIT 1",
        {"hash_id": hash_id},
    ).has_next()


def create_entity_node(conn, label: str, entity) -> None:
    fields = scalar_fields(entity)
    prop_str = ", ".join(f"{k}: ${k}" for k in fields)
    conn.execute(f"CREATE (:{label} {{{prop_str}}})", fields)


def write_provenance(conn, label: str, hash_id: str, prov) -> bool:
    """
    Attach a ProvenanceEntry to an entity, unless this exact source has
    already attested to it. Returns True if a new ProvenanceEntry was added.
    """
    rel = HAS_PROVENANCE_REL[label]
    already = conn.execute(f"""
        MATCH (n:{label} {{hash_id: $hash_id}})-[:{rel}]->(pe:ProvenanceEntry {{source: $source}})
        RETURN pe.uid LIMIT 1
    """, {"hash_id": hash_id, "source": prov.source}).has_next()
    if already:
        return False

    uid = prov.uid or make_uid()
    conn.execute("""
        CREATE (:ProvenanceEntry {
            uid: $uid, source: $source, source_description: $source_description,
            registry_version: $registry_version,
            generated_at: $generated_at, attributed_to: $attributed_to,
            activity: $activity, derived_from: $derived_from
        })
    """, {
        "uid":                uid,
        "source":             prov.source,
        "source_description": prov.source_description,
        "registry_version":   prov.registry_version,
        "generated_at":       prov.generated_at.isoformat(),
        "attributed_to":      prov.attributed_to,
        "activity":           prov.activity,
        "derived_from":       _json.dumps(prov.derived_from),
    })
    conn.execute(f"""
        MATCH (n:{label} {{hash_id: $hash_id}}), (pe:ProvenanceEntry {{uid: $uid}})
        CREATE (n)-[:{rel}]->(pe)
    """, {"hash_id": hash_id, "uid": uid})
    return True


def write_registry_entities(conn, properties: dict, registry_classes: dict,
                             dry_run: bool = False) -> dict:
    """
    Write (or reuse) each property/class node by hash_id, then attach this
    ingestion's ProvenanceEntry to every one of them. Existing nodes are
    never overwritten — a hash match means identical content, so there is
    nothing to update; only a new ProvenanceEntry may need attaching.

    `properties`/`registry_classes` are name -> entity dicts (values just
    need .hash_id and .provenance; shared by ingest_linkml.py and seed.py).
    """
    stats = {
        "properties_new": 0, "properties_existing": 0,
        "classes_new":    0, "classes_existing":    0,
        "provenance_added": 0,
    }

    for prop in properties.values():
        is_new = not entity_exists(conn, "RegistryProperty", prop.hash_id)
        if is_new and not dry_run:
            create_entity_node(conn, "RegistryProperty", prop)
        stats["properties_new" if is_new else "properties_existing"] += 1
        if not dry_run:
            for prov in prop.provenance:
                if write_provenance(conn, "RegistryProperty", prop.hash_id, prov):
                    stats["provenance_added"] += 1

    for rc in registry_classes.values():
        is_new = not entity_exists(conn, "RegistryClass", rc.hash_id)
        if is_new and not dry_run:
            create_entity_node(conn, "RegistryClass", rc)
        stats["classes_new" if is_new else "classes_existing"] += 1
        if not dry_run:
            for prov in rc.provenance:
                if write_provenance(conn, "RegistryClass", rc.hash_id, prov):
                    stats["provenance_added"] += 1

    return stats


def write_structural_edges(conn, registry_classes: dict) -> int:
    """
    HAS_PROPERTY (from each class's own `properties`) + SUBCLASS_OF (from
    `is_a`, which is already resolved to a hash_id or None by the caller).
    """
    rels = 0

    for rc in registry_classes.values():
        for prop_hash_id in rc.properties:
            already = conn.execute("""
                MATCH (c:RegistryClass {hash_id: $c})-[:HAS_PROPERTY]->(p:RegistryProperty {hash_id: $p})
                RETURN c.hash_id LIMIT 1
            """, {"c": rc.hash_id, "p": prop_hash_id}).has_next()
            if not already:
                conn.execute("""
                    MATCH (c:RegistryClass {hash_id: $c}), (p:RegistryProperty {hash_id: $p})
                    CREATE (c)-[:HAS_PROPERTY]->(p)
                """, {"c": rc.hash_id, "p": prop_hash_id})
                rels += 1

    for rc in registry_classes.values():
        parent_hash_id = rc.is_a
        if not parent_hash_id:
            continue

        already = conn.execute("""
            MATCH (c:RegistryClass {hash_id: $c})-[:SUBCLASS_OF]->(p:RegistryClass {hash_id: $p})
            RETURN c.hash_id LIMIT 1
        """, {"c": rc.hash_id, "p": parent_hash_id}).has_next()
        if not already:
            conn.execute("""
                MATCH (c:RegistryClass {hash_id: $c}), (p:RegistryClass {hash_id: $p})
                CREATE (c)-[:SUBCLASS_OF]->(p)
            """, {"c": rc.hash_id, "p": parent_hash_id})
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
    - Non-multivalued class ref → STRING column (hash_id FK).
    - Scalar with db_json or multivalued → STRING (stored as JSON array).
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
            db_json   = slot_def.get("annotations", {}).get("db_json", False)

            if range_ in inline_classes:
                if not multi:
                    for sub_name, sub_def in _resolve_slots(
                        range_, classes, all_slots
                    ).items():
                        sub_range = sub_def.get("range", "string")
                        sub_multi = sub_def.get("multivalued", False)
                        sub_json  = sub_def.get("annotations", {}).get("db_json", False)
                        if sub_range not in classes:
                            if sub_json or sub_multi:
                                columns.append(f"    {sub_name:<24} STRING")
                            else:
                                db_type = _LINKML_TYPE_MAP.get(sub_range, "STRING")
                                columns.append(f"    {sub_name:<24} {db_type}")
                # multivalued inline → not supported; skip

            elif range_ in classes:
                if not multi:
                    # Non-multivalued class ref → STRING FK (hash_id)
                    columns.append(f"    {slot_name:<24} STRING")
                # multivalued → REL table, not a column

            else:
                # Scalar
                if db_json or multi:
                    columns.append(f"    {slot_name:<24} STRING")
                else:
                    db_type = _LINKML_TYPE_MAP.get(range_, "STRING")
                    if is_id:
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

# Registry entity node tables — generated from schemas/meta_model.yaml.
# To add/remove columns: edit the YAML and rebuild the database.
_REGISTRY_NODE_DDL: list[str] = _build_registry_ddl()

# Infrastructure node tables — not part of the meta-model; defined here.
_INFRASTRUCTURE_NODE_DDL: list[str] = [
    # SchemaSource — origin schemas ingested into the registry
    """CREATE NODE TABLE IF NOT EXISTS SchemaSource (
        uid              STRING PRIMARY KEY,
        iri              STRING,
        uri              STRING,
        version          STRING,
        created_at       STRING,
        label            STRING,
        mime_type        STRING,
        registry_version STRING
    )""",

    # SchemaVersionSnapshot — one per (schema_name, semver) pair
    """CREATE NODE TABLE IF NOT EXISTS SchemaVersionSnapshot (
        uid              STRING PRIMARY KEY,
        iri              STRING,
        uri              STRING,
        version          STRING,
        created_at       STRING,
        schema_label     STRING,
        yml_path         STRING,
        class_count      INT64,
        property_count   INT64,
        rule_count       INT64,
        changes_summary  STRING,
        registry_version STRING
    )""",

    # SchemaActivity — PROV-O activity log (defined but not yet written by any script)
    """CREATE NODE TABLE IF NOT EXISTS SchemaActivity (
        uid              STRING PRIMARY KEY,
        iri              STRING,
        uri              STRING,
        version          STRING,
        created_at       STRING,
        activity         STRING,
        agent            STRING,
        started_at       STRING,
        issue_number     STRING,
        registry_version STRING
    )""",

    # SemanticIdentity — canonical node per unique content hash for cross-source dedup
    """CREATE NODE TABLE IF NOT EXISTS SemanticIdentity (
        uid           STRING PRIMARY KEY,
        content_id    STRING,
        canonical_uri STRING,
        datatype      STRING,
        units         STRING,
        iri           STRING,
        created_at    STRING
    )""",
]

# Relationship tables — multivalued meta-model edges + alignment infrastructure.
_REL_DDL: list[str] = [
    # --- Meta-model multivalued edges ---
    "CREATE REL TABLE IF NOT EXISTS HAS_PROPERTY       (FROM RegistryClass    TO RegistryProperty)",
    "CREATE REL TABLE IF NOT EXISTS HAS_RELATION       (FROM RegistryClass    TO Relation)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING   (FROM RegistryClass    TO SkosMapping)",
    "CREATE REL TABLE IF NOT EXISTS HAS_SKOS_MAPPING_P (FROM RegistryProperty TO SkosMapping)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE     (FROM RegistryClass    TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_P   (FROM RegistryProperty TO ProvenanceEntry)",
    "CREATE REL TABLE IF NOT EXISTS HAS_PROVENANCE_R   (FROM Relation         TO ProvenanceEntry)",
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
        FROM Rule TO Rule,
        diff_summary        STRING,
        changed_fields      STRING,
        registry_version    STRING,
        created_at          STRING
    )""",

    # --- Infrastructure edges ---
    "CREATE REL TABLE IF NOT EXISTS APPLIES_TO         (FROM Rule             TO RegistryClass)",
    "CREATE REL TABLE IF NOT EXISTS PROV_GENERATED     (FROM RegistryClass    TO SchemaActivity)",
    "CREATE REL TABLE IF NOT EXISTS PROV_GENERATED_P   (FROM RegistryProperty TO SchemaActivity)",
    "CREATE REL TABLE IF NOT EXISTS PROV_GENERATED_R   (FROM Rule             TO SchemaActivity)",
    "CREATE REL TABLE IF NOT EXISTS FROM_SOURCE        (FROM RegistryClass    TO SchemaSource)",
    "CREATE REL TABLE IF NOT EXISTS FROM_SOURCE_P      (FROM RegistryProperty TO SchemaSource)",
    "CREATE REL TABLE IF NOT EXISTS HAS_IDENTITY       (FROM RegistryClass    TO SemanticIdentity)",
    "CREATE REL TABLE IF NOT EXISTS HAS_IDENTITY_P     (FROM RegistryProperty TO SemanticIdentity)",

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

DDL = _REGISTRY_NODE_DDL + _INFRASTRUCTURE_NODE_DDL + _REL_DDL


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

def _migrate_aligned_to(conn: lb.Connection) -> None:
    """Drop and recreate ALIGNED_TO if it lacks current columns."""
    try:
        conn.execute("""
            MATCH (a:RegistryClass), (b:RegistryClass)
            WHERE a.hash_id <> b.hash_id
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
            WHERE a.hash_id <> b.hash_id
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
            WHERE a.hash_id <> b.hash_id
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
