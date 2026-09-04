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
For every class→slot relationship → one HAS_PROPERTY edge
For every is_a relationship → one SUBCLASS_OF edge
For every schema file → one SchemaSource node + one SchemaVersionSnapshot
For every (entity, source) attestation → one ProvenanceEntry node,
  linked via HAS_PROVENANCE / HAS_PROVENANCE_P

CONTENT-ADDRESSED IDENTITY
---------------------------
A RegistryClass/RegistryProperty's sha256_hash is computed from its own semantic
content (name, description for properties — a property is a pure concept, so
its value type and unit live on RegistryRules, not in its identity; name,
description, properties/is_a/mixins for classes) — see
schema_registry_utils.hashing.
Two properties from different schemas with identical content get the SAME
sha256_hash automatically; there is no separate content_id/SemanticIdentity
lookup layer anymore.

Identity is separate from provenance: ingesting the same content from a
second source doesn't create a second node, it adds a second ProvenanceEntry
to the existing one. There is no "version" or diff mechanism — a genuine
content change produces a different sha256_hash (a new entity), not an edit of
the old one.

USAGE
-----
  python ingest_linkml.py --file registry_schemas/bbqs.yml
  python ingest_linkml.py                          # all registry_schemas/*.yml
  python ingest_linkml.py --dry-run                # preview, no writes
  python ingest_linkml.py --wipe --file registry_schemas/bbqs.yml  # remove this source's
                                                            # attestations first
"""

from __future__ import annotations
import re, sys, tempfile
from pathlib import Path
from typing import Any

import click
from linkml_runtime.utils.schemaview import SchemaView

# Same-directory import — Python puts the script's own dir on sys.path[0]
# when this file is invoked as `python neuro_ghost/ingest_linkml.py`, which
# is how the CLI is run today. `from db import ...` below relies on the
# same mechanism.
from import_resolver import resolve_external_imports

sys.path.insert(0, str(Path(__file__).parent.parent))
from schema_registry_utils import (
    RegistryClass, RegistryProperty, PermissibleValue, RegistryValueSet,
    RegistryRule, ProvenanceEntry, compute_content_hash_for,
)

from db import (
    get_connection, make_iri, make_id, now_iso,
    write_registry_entities, write_structural_edges, write_rule_edges,
    ensure_schema_source, find_id_by_sha256, find_duplicate_source,
)
from source_metadata import load_source_sidecar
from schema_hash import content_hash


def _source_metadata(parsed: dict) -> dict:
    """SchemaSource descriptive metadata, keyed by slot name: `title` and
    `source_id` propagated from the schema's own `title:`/`id:`, overlaid with
    its optional `<stem>_source.yaml` sidecar (publisher/contact/homepage/
    source_iri/…, which may also override the propagated values)."""
    meta = parsed.get("meta", {})
    return {
        "title": meta.get("title", ""),
        "source_id": meta.get("id", ""),
        "content_hash": meta.get("content_hash", ""),
        **(parsed.get("source_metadata") or {}),
    }

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
    "time":       "xsd:time",
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

def _map_range(raw_range: str, prefixes: dict[str, str]) -> str:
    """Map a single LinkML range name to our stored form: an XSD CURIE for a
    primitive, otherwise a resolved IRI (a real CURIE resolved, or a synthetic
    make_iri(name) placeholder that build_registry_entities' second pass
    rewrites to the target's real id)."""
    if raw_range in LINKML_PRIMITIVES:
        return LINKML_PRIMITIVES[raw_range]
    return (resolve_prefix(raw_range, prefixes)
            if ":" in raw_range else make_iri(raw_range))


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

    # Range is multivalued: a plain slot has one range; a union (LinkML
    # `any_of`) has several. Collect them all into one list — a union is just
    # a property with more than one permitted range, not a separate field.
    any_of = [m.range for m in (slot.any_of or []) if getattr(m, "range", None)]
    if any_of:
        value_range = [_map_range(r, prefixes) for r in any_of]
    else:
        raw_range = slot.range if isinstance(slot.range, str) and slot.range else "string"
        value_range = [_map_range(raw_range, prefixes)]

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
        "minimum_value": None if slot.minimum_value is None else str(slot.minimum_value),
        "maximum_value": None if slot.maximum_value is None else str(slot.maximum_value),
        "aliases":     list(slot.aliases or []),
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
    # If the submitted schema declares an `annotations.imports_source`
    # URL, fetch every external import (recursively) into a temp
    # directory alongside a copy of the schema before SchemaView sees it.
    # A schema without that annotation returns from resolve_external_imports
    # unchanged, so pre-annotation schemas (bbqs, bids, …) go through as
    # before. See neuro_ghost/import_resolver.py for the contract.
    with tempfile.TemporaryDirectory(prefix="ng-imports-") as _work:
        resolved_path = resolve_external_imports(path, Path(_work))
        sv = SchemaView(str(resolved_path))
        parsed = _parse_schemaview(sv, path)
    return parsed


def _parse_schemaview(sv, path: Path) -> dict[str, Any]:
    """The core of parse_linkml — pulled out so the SchemaView instance
    can be built inside a temp-dir context and this body runs before the
    temp dir is cleaned up."""
    prefixes = {k: v.prefix_reference for k, v in (sv.schema.prefixes or {}).items()}

    meta = {
        "id":          sv.schema.id or "",
        "name":        sv.schema.name or path.stem,
        "title":       sv.schema.title or "",
        "version":     str(sv.schema.version or "1.0.0"),
        "description": sv.schema.description or "",
        # File-level fingerprint of the raw source text (canonicalised) — lets
        # ingestion reject a schema that is already in the registry, and lets
        # the UI pre-check a dropped/pasted file. See schema_hash.py.
        "content_hash": content_hash(Path(path).read_text()),
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

        # Same dangling-reference handling for mixins as is_a above.
        mixins = []
        for mixin_name in (cls_def.mixins or []):
            try:
                sv.get_class(mixin_name)
                mixins.append(mixin_name)
            except (ValueError, KeyError):
                pass

        classes[cls_name] = {
            "iri":         resolved_iri,
            "definition":  cls_def.description or "",
            "is_a":        is_a,
            "is_abstract": bool(cls_def.abstract),
            "is_mixin":    bool(cls_def.mixin),
            "mixins":      mixins,
            "slots":       [slot.name for slot in induced_slots],
            "aliases":     list(cls_def.aliases or []),
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
        # Optional per-schema source-metadata sidecar (<stem>_source.yaml).
        "source_metadata": load_source_sidecar(path),
    }


# ---------------------------------------------------------------------------
# Parsed dict → content-hashed RegistryClass / RegistryProperty
# ---------------------------------------------------------------------------

def _make_provenance(schema_source_id: str, attests_to: str, agent: str,
                     issue: str = "", registry_version: str = "",
                     source_version: str = "",
                     activity: str = "ingestion") -> ProvenanceEntry:
    attributed_to = f"{agent} (issue #{issue})" if issue else agent
    return ProvenanceEntry(
        id=make_id(),
        attests_to=attests_to,
        had_primary_source=schema_source_id,
        source_version=source_version or None,
        registry_version=registry_version or None,
        generated_at_time=now_iso(),
        was_attributed_to=attributed_to,
        was_generated_by=activity,
        was_derived_from=[],
    )


def build_registry_entities(
    parsed: dict, schema_source_id: str, agent: str, issue: str = "",
    registry_version: str = "", conn=None,
) -> tuple[
    dict[str, RegistryProperty],
    dict[str, RegistryClass],
    dict[str, RegistryValueSet],
    dict[str, PermissibleValue],
    dict[str, RegistryRule],
    dict[str, ProvenanceEntry],
]:
    """
    Convert parse_linkml()'s intermediate dict into RegistryProperty/
    RegistryClass instances, keyed by their original slot/class name in the
    source schema. permissible_values (the 4th return value) is keyed by
    id instead, since PermissibleValue is shared across enums/sources
    rather than tied to one source name.

    Identity is now split from content:
      * `id` is a UUID minted by uuid.uuid4() (via db.make_id()) — the
        graph's stable handle for FKs.
      * `sha256_hash` is the content fingerprint, still computed from
        HashSubset-marked fields the same way as before.

    Cross-source deduplication happens via sha256_hash lookup: for each
    entity, compute the content hash first, then either reuse an existing
    row's id (if any row already carries that sha256_hash) or mint a fresh
    uuid4. `conn` is optional — passed in during real ingestion so the
    dedup can consult the graph; omitted from unit tests, in which case
    every entity gets a fresh UUID and dedup happens on next re-ingest.

    Properties are built first because classes reference them by id in
    their own `properties` list, and those ids must exist before the
    class's own sha256_hash can be computed (the id list is part of the
    class's HashSubset — same-content classes across sources hash the
    same because their property ids were reused via dedup).

    A class's `is_a` is resolved to its parent's id recursively, so
    multi-level hierarchies resolve correctly regardless of declaration
    order. This always succeeds for any schema that reaches this point:
    parse_linkml() (via SchemaView) already requires every is_a target to
    resolve within the submitted schema's own import closure, so `classes`
    is guaranteed to contain it.
    """
    slots   = parsed["slots"]
    classes = parsed["classes"]
    source_version = parsed.get("meta", {}).get("version") or ""

    used_slots: set[str] = set()
    for cls in classes.values():
        used_slots.update(cls["slots"])

    # ProvenanceEntry is a separate node in the graph (linked via
    # HAS_PROVENANCE/HAS_PROVENANCE_P), and the meta_model now reflects
    # that: RegistryEntity.provenance stores ProvenanceEntry.id references,
    # not embedded objects. Collect the entries here and return them
    # alongside the entities so the writers can persist both.
    provenance_entries: dict[str, ProvenanceEntry] = {}

    def make_prov(attests_to: str) -> str:
        """Build a ProvenanceEntry, store it in the collection, and return
        its id — for use as a reference in the parent entity's `provenance`
        list."""
        pe = _make_provenance(
            schema_source_id, attests_to, agent, issue,
            registry_version, source_version,
        )
        provenance_entries[pe.id] = pe
        return pe.id

    def dedup_id(kind: str, sha: str) -> str:
        """Return an existing id for this sha256_hash if the graph already
        has one, otherwise mint a fresh UUID. `conn` may be None (unit
        tests, dry-run) — in which case dedup is skipped and each entity
        gets its own uuid, converging on the next real ingest."""
        if conn is not None:
            existing = find_id_by_sha256(conn, kind, sha)
            if existing:
                return existing
        return make_id()

    properties: dict[str, RegistryProperty] = {}
    for slot_name in used_slots:
        slot = slots.get(slot_name)
        if not slot:
            continue
        # A RegistryProperty is a pure concept: identity is name + description
        # only. The value type(s) (property_range) and unit are NOT stored
        # here — they are realization details recorded as RANGE / UNIT
        # RegistryRules below (one RANGE rule per permitted range), so the same
        # concept collapses across schemas even when they type or measure it
        # differently.
        fields = dict(
            name=slot_name,
            description=slot["definition"] or "",
            concept_uri=slot["iri"] or None,
            skos_mappings=[],
            aliases=slot.get("aliases") or [],
        )
        sha = compute_content_hash_for(RegistryProperty, fields)
        pid = dedup_id("RegistryProperty", sha)
        prop = RegistryProperty(
            id=pid,
            sha256_hash=sha,
            provenance=[make_prov(pid)],
            **fields,
        )
        properties[slot_name] = prop

    registry_classes: dict[str, RegistryClass] = {}

    def resolve_class(cls_name: str) -> RegistryClass | None:
        if cls_name in registry_classes:
            return registry_classes[cls_name]
        cls = classes.get(cls_name)
        if cls is None:
            return None  # is_a points outside this schema — left unresolved

        parent_id = None
        if cls["is_a"]:
            parent = resolve_class(cls["is_a"])
            parent_id = parent.id if parent else None

        mixin_ids = sorted({
            mixin.id for m in cls.get("mixins", [])
            if (mixin := resolve_class(m)) is not None
        })

        prop_ids = sorted({
            properties[s].id for s in cls["slots"] if s in properties
        })
        fields = dict(
            name=cls_name,
            description=cls["definition"] or "",
            concept_uri=cls["iri"] or None,
            is_abstract=cls["is_abstract"],
            is_mixin=cls["is_mixin"],
            parent_class=parent_id,
            properties=prop_ids,
            class_mixins=mixin_ids,
            skos_mappings=[],
            aliases=cls.get("aliases") or [],
        )
        sha = compute_content_hash_for(RegistryClass, fields)
        cid = dedup_id("RegistryClass", sha)
        rc = RegistryClass(
            id=cid,
            sha256_hash=sha,
            provenance=[make_prov(cid)],
            **fields,
        )
        registry_classes[cls_name] = rc
        return rc

    for cls_name in classes:
        resolve_class(cls_name)

    # Build PermissibleValue + RegistryValueSet instances from parsed enums.
    prov_factory = make_prov
    value_sets: dict[str, RegistryValueSet] = {}
    permissible_values: dict[str, PermissibleValue] = {}

    for enum_name, enum_data in parsed.get("enums", {}).items():
        pv_ids: list[str] = []
        for pv_text, pv_data in enum_data["permissible_values"].items():
            pv_fields = dict(
                name=pv_text,
                description=pv_data["description"] or "",
                meaning=pv_data["meaning"] or None,
                skos_mappings=[],
                aliases=[],
            )
            pv_sha = compute_content_hash_for(PermissibleValue, pv_fields)
            pv_id = dedup_id("PermissibleValue", pv_sha)
            if pv_id not in permissible_values:
                permissible_values[pv_id] = PermissibleValue(
                    id=pv_id,
                    sha256_hash=pv_sha,
                    provenance=[prov_factory(pv_id)],
                    **pv_fields,
                )
            pv_ids.append(pv_id)

        vs_fields = dict(
            name=enum_name,
            description=enum_data["definition"] or "",
            permissible_values=sorted(pv_ids),
            skos_mappings=[],
        )
        vs_sha = compute_content_hash_for(RegistryValueSet, vs_fields)
        vs_id = dedup_id("RegistryValueSet", vs_sha)
        vs = RegistryValueSet(
            id=vs_id,
            sha256_hash=vs_sha,
            provenance=[prov_factory(vs_id)],
            **vs_fields,
        )
        value_sets[enum_name] = vs

    # RegistryRules — built LAST, after properties, classes, and enums all
    # have ids, so a rule that references another entity (a RANGE rule whose
    # value is a class/enum) can carry that entity's real id directly. This
    # ordering is what makes range/unit-on-rules cycle-free: property and
    # class hashes settle first (their identity no longer depends on range or
    # unit), then rules point at the settled ids. No second pass, no SELF
    # sentinel — a self-referential range (ProvEntity.was_derived_from ->
    # ProvEntity) is just a RANGE rule whose rule_value is ProvEntity's id,
    # and the class hash never depended on that rule.
    #
    # A class/enum-typed range arrives from _slot_to_dict() as make_iri(name)
    # (a synthetic label, not a graph reference); resolve it to the real id
    # here. An XSD CURIE or an already-resolved external IRI passes through.
    name_iri_to_id: dict[str, str] = {
        make_iri(cls_name): rc.id
        for cls_name, rc in registry_classes.items()
    }
    name_iri_to_id.update({
        make_iri(enum_name): vs.id
        for enum_name, vs in value_sets.items()
    })

    def resolve_range(value: str) -> str:
        """XSD CURIE / external IRI pass through; a make_iri(name) placeholder
        for an in-schema class or enum resolves to that entity's real id."""
        return name_iri_to_id.get(value, value)

    # One RegistryRule per declarative facet a slot states, atomic per
    # rule_type (see RegistryRuleTypeEnum). REQUIRED/PATTERN/MIN_VALUE/
    # MAX_VALUE come from the facets parse_linkml() extracts; RANGE carries the
    # value type (one rule per permitted range — a union is several RANGE
    # rules); UNIT carries the unit. The remaining rule_types (MAX_LENGTH,
    # ENUM_MEMBERSHIP, ...) aren't wired up yet and need their own
    # parse_linkml() extraction first.
    _RULE_TYPE_DESCRIPTIONS = {
        "REQUIRED": "Property must be present.",
        "PATTERN": "Value must match a regex.",
        "MIN_VALUE": "Numeric value must satisfy a lower bound (inclusive).",
        "MAX_VALUE": "Numeric value must satisfy an upper bound (inclusive).",
        "RANGE": "One permitted value type for the property in this usage.",
        "UNIT": "Unit of measure for the property's values in this usage.",
    }

    rules: dict[str, RegistryRule] = {}

    def make_rule(slot_name: str, rule_type: str, rule_value: str, error_message: str) -> None:
        fields = dict(
            name=rule_type,
            description=_RULE_TYPE_DESCRIPTIONS[rule_type],
            skos_mappings=[],
            aliases=[],
            concept_uri=None,
            rule_type=rule_type,
            rule_value=rule_value,
            applies_to=[properties[slot_name].id],
            used_in_class=None,
            severity="ERROR",
            error_message=error_message,
            referenced_entities=[],
        )
        sha = compute_content_hash_for(RegistryRule, fields)
        rid = dedup_id("RegistryRule", sha)
        rule = RegistryRule(
            id=rid,
            sha256_hash=sha,
            provenance=[make_prov(rid)],
            **fields,
        )
        # Key by rule_value too where a slot can state several rules of the
        # same type (a union's RANGE rules), so members don't overwrite each
        # other; single-instance types keep the plain "slot:TYPE" key.
        key = f"{slot_name}:{rule_type}"
        if key in rules:
            key = f"{slot_name}:{rule_type}:{rule_value}"
        rules[key] = rule

    for slot_name, prop in properties.items():
        slot = slots[slot_name]
        if slot.get("required"):
            make_rule(slot_name, "REQUIRED", "true", f"{slot_name} is required.")
        if slot.get("pattern"):
            make_rule(slot_name, "PATTERN", slot["pattern"],
                      f"{slot_name} must match pattern {slot['pattern']!r}.")
        if slot.get("minimum_value") is not None:
            make_rule(slot_name, "MIN_VALUE", slot["minimum_value"],
                      f"{slot_name} must be >= {slot['minimum_value']}.")
        if slot.get("maximum_value") is not None:
            make_rule(slot_name, "MAX_VALUE", slot["maximum_value"],
                      f"{slot_name} must be <= {slot['maximum_value']}.")

        # Value type: one RANGE rule per permitted range. A single-range slot
        # makes one; a union (property_range with several entries) makes one
        # per member — no separate rule_type.
        for member in slot.get("value_range") or []:
            rv = resolve_range(member)
            make_rule(slot_name, "RANGE", rv, f"{slot_name} has range {rv}.")

        # Unit: rule_value is the UCUM short code parse_linkml() extracted
        # ("FTE", "mV", "Hz") — the shape align.py's unit veto expects.
        unit_text = slot.get("units") or None
        if unit_text:
            make_rule(slot_name, "UNIT", unit_text, f"{slot_name} is measured in {unit_text}.")

    return properties, registry_classes, value_sets, permissible_values, rules, provenance_entries


# ---------------------------------------------------------------------------
# Graph writers
# ---------------------------------------------------------------------------
# entity_exists / create_entity_node / write_provenance / write_registry_entities
# / write_structural_edges all live in db.py — shared with seed.py, which
# writes the same two node types the same way.


# ---------------------------------------------------------------------------
# RegistryValueSet / PermissibleValue graph writers
# ---------------------------------------------------------------------------

def _write_value_sets(conn, value_sets: dict[str, "RegistryValueSet"],
                      permissible_values: dict[str, "PermissibleValue"],
                      provenance_entries: dict[str, "ProvenanceEntry"]) -> int:
    """
    Write RegistryValueSet and PermissibleValue nodes + edges. Returns edge count.

    Provenance is passed in via `provenance_entries` (id → ProvenanceEntry)
    because RegistryEntity.provenance is now a list of ids, not embedded
    objects — the pydantic model matches the graph shape.
    """
    from db import entity_exists, create_entity_node, write_provenance

    rels = 0
    for enum_name, vs in value_sets.items():
        is_new = not entity_exists(conn, "RegistryValueSet", vs.id)
        if is_new:
            create_entity_node(conn, "RegistryValueSet", vs)
        for prov_id in vs.provenance:
            write_provenance(conn, "RegistryValueSet", vs.id, provenance_entries[prov_id])

        # Write each PermissibleValue node and link it.
        for pv_id in vs.permissible_values:
            pv = permissible_values[pv_id]
            pv_is_new = not entity_exists(conn, "PermissibleValue", pv.id)
            if pv_is_new:
                create_entity_node(conn, "PermissibleValue", pv)
            for prov_id in pv.provenance:
                write_provenance(conn, "PermissibleValue", pv.id, provenance_entries[prov_id])

            edge_exists = conn.execute("""
                MATCH (vs:RegistryValueSet {id: $vs})-[:HAS_PERMISSIBLE_VALUE]->(pv:PermissibleValue {id: $pv})
                RETURN vs.id LIMIT 1
            """, {"vs": vs.id, "pv": pv.id}).has_next()
            if not edge_exists:
                conn.execute("""
                    MATCH (vs:RegistryValueSet {id: $vs}), (pv:PermissibleValue {id: $pv})
                    CREATE (vs)-[:HAS_PERMISSIBLE_VALUE]->(pv)
                """, {"vs": vs.id, "pv": pv.id})
                rels += 1

    return rels


# TODO: _write_skos_mappings() — not implemented yet. skos_mappings is hardcoded
# to [] everywhere in build_registry_entities() below; HAS_SKOS_MAPPING /
# HAS_SKOS_MAPPING_P edges are declared in db.py's DDL but have no writer.
# Source from the input schema's own exact_mappings/close_mappings/
# related_mappings/narrow_mappings/broad_mappings (LinkML's own mapping
# slots) once a real schema actually declares them — none do yet.


# ---------------------------------------------------------------------------
# SchemaSource / SchemaVersionSnapshot (unchanged in spirit from before)
# ---------------------------------------------------------------------------

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

      1. Build content-hashed RegistryProperty/RegistryClass instances
      2. Write each one (skipped if its id already exists) and attach
         this ingestion's ProvenanceEntry (skipped if this source already
         attested to it)
      3. Create HAS_PROPERTY and SUBCLASS_OF edges
      4. Record a SchemaVersionSnapshot — "minor" if any class/property was
         newly created, "patch" if only a new ProvenanceEntry was added
         (same content, newly attested by this source), unchanged otherwise

    Returns a stats dict.
    """
    meta = parsed["meta"]
    schema_hash = meta.get("content_hash", "")

    # Reject a file whose exact content is already in the registry under a
    # different source label — the schema was already added (see
    # find_duplicate_source). Re-ingesting the SAME label is an update, not a
    # duplicate, and falls through to the normal schema_unchanged path below.
    if not dry_run:
        dup = find_duplicate_source(conn, schema_hash, exclude_label=source_label)
        if dup:
            return {
                "classes_new": 0, "classes_existing": 0,
                "properties_new": 0, "properties_existing": 0,
                "provenance_added": 0, "rels": 0,
                "duplicate_of": dup, "skipped": True,
                "content_hash": schema_hash,
            }

    # SchemaSource must exist before any ProvenanceEntry is built, since
    # had_primary_source is a real FK to it — including in dry-run, which
    # gets a throwaway placeholder id instead of writing anything.
    schema_source_id = ensure_schema_source(
        conn, source_label, meta["version"], registry_version, dry_run=dry_run,
        metadata=_source_metadata(parsed),
    )

    properties, registry_classes, value_sets, permissible_values, rules, provenance_entries = build_registry_entities(
        parsed, schema_source_id, agent, issue, registry_version, conn=conn,
    )

    stats = write_registry_entities(
        conn, properties, registry_classes, rules, provenance_entries, dry_run=dry_run,
    )

    if dry_run:
        return stats

    stats["rels"] = write_structural_edges(conn, registry_classes)
    stats["rels"] += write_rule_edges(conn, rules, registry_classes, properties)
    stats["rels"] += _write_value_sets(conn, value_sets, permissible_values, provenance_entries)

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

    snap_id = make_id()
    conn.execute("""
        CREATE (:SchemaVersionSnapshot {
            id: $id, source_version: $source_version, created_at: $created_at,
            schema_label: $sl, yml_path: $yp,
            class_count: $cc, property_count: $pc,
            changes_summary: $cs, registry_version: $rv
        })
    """, {
        "id":             snap_id,
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

def _print_entities(properties: dict, registry_classes: dict,
                    value_sets: dict, permissible_values: dict,
                    rules: dict, provenance_entries: dict,
                    readable: bool = False) -> None:
    """
    Pretty-print the entities build_registry_entities() would create, for
    visual inspection.

    By default prints exactly what is stored — id-reference fields
    (properties, parent_class, applies_to, rule_value range targets,
    attests_to, ...) show the raw UUIDs. With readable=True those references
    are resolved to the referent's name instead, for eyeballing.
    """
    name_by_id = {p.id: name for name, p in properties.items()}
    name_by_id.update({c.id: name for name, c in registry_classes.items()})
    name_by_id.update({vs.id: name for name, vs in value_sets.items()})
    name_by_id.update({pv.id: pv.name for pv in permissible_values.values()})

    def ref(x):
        return name_by_id.get(x, x) if readable else x

    def refs(xs):
        return [ref(x) for x in xs]

    if registry_classes:
        click.echo("  --- RegistryClass ---")
        for name, c in registry_classes.items():
            click.echo(f"  {name}")
            click.echo(f"      id:            {c.id}")
            click.echo(f"      sha256_hash:   {c.sha256_hash}")
            click.echo(f"      description:   {c.description}")
            click.echo(f"      concept_uri:   {c.concept_uri}")
            click.echo(f"      is_abstract:   {c.is_abstract}")
            click.echo(f"      is_mixin:      {c.is_mixin}")
            click.echo(f"      parent_class:  {ref(c.parent_class)}")
            click.echo(f"      class_mixins:  {refs(c.class_mixins)}")
            click.echo(f"      properties:    {refs(c.properties)}")
            click.echo(f"      aliases:       {c.aliases}")

    if properties:
        click.echo("  --- RegistryProperty ---")
        for name, p in properties.items():
            click.echo(f"  {name}")
            click.echo(f"      id:            {p.id}")
            click.echo(f"      sha256_hash:   {p.sha256_hash}")
            click.echo(f"      description:   {p.description}")
            click.echo(f"      concept_uri:   {p.concept_uri}")
            click.echo(f"      aliases:       {p.aliases}")

    if value_sets:
        click.echo("  --- RegistryValueSet ---")
        for name, vs in value_sets.items():
            click.echo(f"  {name}")
            click.echo(f"      id:                 {vs.id}")
            click.echo(f"      sha256_hash:        {vs.sha256_hash}")
            click.echo(f"      permissible_values: {refs(vs.permissible_values)}")

    if rules:
        click.echo("  --- RegistryRule ---")
        for key, r in rules.items():
            click.echo(f"  {key}")
            click.echo(f"      id:                  {r.id}")
            click.echo(f"      sha256_hash:         {r.sha256_hash}")
            click.echo(f"      rule_type:           {r.rule_type}")
            click.echo(f"      rule_value:          {r.rule_value}")
            click.echo(f"      applies_to:          {refs(r.applies_to)}")
            click.echo(f"      used_in_class:       {ref(r.used_in_class)}")
            click.echo(f"      severity:            {r.severity}")
            click.echo(f"      error_message:       {r.error_message}")

    if provenance_entries:
        click.echo("  --- ProvenanceEntry ---")
        for pe in provenance_entries.values():
            click.echo(f"  {pe.id}")
            click.echo(f"      attests_to:         {ref(pe.attests_to)}")
            click.echo(f"      had_primary_source: {pe.had_primary_source}")
            click.echo(f"      source_version:     {pe.source_version}")
            click.echo(f"      registry_version:   {pe.registry_version}")
            click.echo(f"      generated_at_time:  {pe.generated_at_time}")
            click.echo(f"      was_attributed_to:  {pe.was_attributed_to}")
            click.echo(f"      was_generated_by:   {pe.was_generated_by}")
            click.echo(f"      was_derived_from:   {pe.was_derived_from}")


@click.command()
@click.option("--file",    default=None,
              help="Path to a specific .yml file. Default: all registry_schemas/*.yml")
@click.option("--db",      default=DB_PATH, show_default=True)
@click.option("--dry-run", is_flag=True,
              help="Parse and count without writing to DB.")
@click.option("--verbose", is_flag=True,
              help="Print each built entity in full, exactly as stored — "
                   "id-reference fields (properties, ranges, ...) show raw "
                   "UUIDs. Pairs well with --dry-run.")
@click.option("--verbose-readable", is_flag=True,
              help="Like --verbose, but resolve id references to the "
                   "referent's name for easier reading.")
@click.option("--wipe",    is_flag=True,
              help="Remove this source's attestations before re-ingesting.")
@click.option("--registry-version", default="",
              help="Registry semver to stamp on created nodes.")
@click.option("--issue",   default="", help="GitHub issue number (for provenance).")
@click.option("--agent",   default="anonymous", help="Who submitted this schema.")
def cli(file, db, dry_run, verbose, verbose_readable, wipe,
        registry_version, issue, agent) -> None:
    """
    Ingest one or more LinkML .yml schemas into the NeuroGhost graph.

    Examples:
      python ingest_linkml.py --file registry_schemas/bbqs.yml
      python ingest_linkml.py --file registry_schemas/bids.yml --dry-run
      python ingest_linkml.py --file registry_schemas/bbqs.yml --dry-run --verbose
      python ingest_linkml.py --wipe --file registry_schemas/nwb.yml
    """
    conn = get_connection(db)

    if file:
        files = [Path(file)]
    else:
        schemas_dir = Path("registry_schemas")
        if not schemas_dir.exists():
            click.echo("No registry_schemas/ directory. Use --file or create registry_schemas/.")
            return
        files = sorted(schemas_dir.glob("*.yml"))
        if not files:
            click.echo("No .yml files in registry_schemas/")
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
                MATCH (:RegistryClass)-[:HAS_PROVENANCE]->(pe:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(:SchemaSource {label: $src})
                DETACH DELETE pe
            """, {"src": source_label})
            conn.execute("""
                MATCH (:RegistryProperty)-[:HAS_PROVENANCE_P]->(pe:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(:SchemaSource {label: $src})
                DETACH DELETE pe
            """, {"src": source_label})

        if verbose or verbose_readable:
            # Read-only preview build — uses the real ensure_schema_source
            # (safe: it only reads/creates the SchemaSource, no
            # RegistryClass/RegistryProperty writes happen here) and the
            # real conn for dedup lookups, so ids shown here match what a
            # subsequent non-dry-run insert_schema() would actually produce.
            preview_source_id = ensure_schema_source(
                conn, source_label, parsed["meta"]["version"],
                registry_version, dry_run=dry_run,
                metadata=_source_metadata(parsed),
            )
            p_props, p_classes, p_vs, p_pvs, p_rules, p_provs = build_registry_entities(
                parsed, preview_source_id, agent, issue, registry_version, conn=conn,
            )
            _print_entities(p_props, p_classes, p_vs, p_pvs, p_rules, p_provs,
                            readable=verbose_readable)

        stats = insert_schema(
            conn, parsed, source_label, agent=agent, issue=issue,
            dry_run=dry_run,
            registry_version=registry_version,
            yml_path=str(path),
        )

        if stats.get("skipped") and stats.get("duplicate_of"):
            click.echo(f"  Skipped — identical content already ingested as "
                       f"'{stats['duplicate_of']}'. Not re-added.")
            continue

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
