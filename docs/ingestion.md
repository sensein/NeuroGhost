# How schema ingestion works

> **Status: living document.** Reflects the current state of ingestion —
> identity split into a UUID `id` (primary key) and a `sha256_hash` content
> fingerprint (drives dedup). Treat this as the current source of truth,
> not a historical record.

## The problem this solves

Every neuroscience data standard (BIDS, NWB, DANDI, openMINDS, AIND, ...)
defines its own vocabulary. The same concept — "age", "subject", "device
manufacturer" — gets redefined independently in each one, usually under a
different name, attached to a different class. The registry's job is to
notice when two things from different schemas are actually the same concept,
without a human manually saying so for every pair.

An earlier design just gave every ingested class/property a random UUID and
tracked "is this the same as before" by looking up `(iri, source_label)` and
diffing fields by hand. That only ever compared a schema against *its own*
prior ingestions — it had no way to notice that two *different* schemas
defined the same thing.

## The core idea: identity by UUID, dedup by content hash

Every registered object carries two identity-related fields:

- **`id`** — a UUID (`uuid4`), the primary key. Uniform across
  `RegistryEntity` subclasses and non-content-addressed classes
  (`ProvenanceEntry`, `SchemaSource`, `SchemaVersionSnapshot`, `Mapping`,
  `RegistrySchema`, ...), so cross-references are the same shape regardless
  of the referent's family — `RegistryClass.properties`, `parent_class`,
  `class_mixins`, `RegistryRule.applies_to` (and a RANGE rule's class/enum
  `rule_value`), and `ProvenanceEntry.attests_to` are all UUIDs.
- **`sha256_hash`** — a content fingerprint on `RegistryEntity` subclasses,
  computed from the fields marked `in_subset: HashSubset` in
  `meta_model.yaml`. Not the identifier — but the mechanism by
  which two sources' identical concepts collapse to one row: on ingest,
  `build_registry_entities` computes each entity's `sha256_hash` first,
  then either reuses an existing row's `id` (via `find_id_by_sha256`) or
  mints a fresh UUID. Same content → same `sha256_hash` → same `id`.

```
schema_a.yml: Subject.age  (name=age, description=..., range=integer)
schema_b.yml: Participant.age  (same content, different class)
                    │
                    ▼
        ONE RegistryProperty node
          id           = <uuid4 minted at first ingest, reused at second>
          sha256_hash  = <content fingerprint, identical for both sources>
          provenance   = [<uuid of ProvenanceEntry for source_a>,
                          <uuid of ProvenanceEntry for source_b>]
```

Identity is separate from provenance: ingesting the same content from a
second source doesn't create a second entity node, it adds a second
`ProvenanceEntry` node linked to the existing entity via `HAS_PROVENANCE` /
`HAS_PROVENANCE_P`. A genuine content change produces a different
`sha256_hash` (a new entity, new UUID), not an edit of the old one.

No alignment step, no manual annotation — pure hash equality gives you this
for free. (Real alignment — noticing that *differently*-named/described
concepts are related — is a separate, deliberately basic step for now; see
[Alignment](#alignment) below.)

## The pipeline

```
LinkML YAML
    │  resolve_external_imports() — fetch declared external imports
    │                              (see "External imports" below)
    │  parse_linkml()             — SchemaView-based parsing
    ▼
intermediate dict               {classes: {...}, slots: {...}, enums: {...}}
    │  build_registry_entities() — compute sha256_hash, dedup or mint id,
    │                              build ProvenanceEntry per attestation
    ▼
RegistryProperty / RegistryClass / RegistryValueSet / PermissibleValue instances
    (Pydantic; id + sha256_hash set; .provenance is a list of ProvenanceEntry.id)
+ provenance_entries: dict[str, ProvenanceEntry]   ← returned alongside
    │  write_registry_entities()  — write-if-new, attach-provenance-if-new
    │  write_structural_edges()   — HAS_PROPERTY, SUBCLASS_OF
    │  _write_value_sets()        — RegistryValueSet + PermissibleValue nodes,
    │                                HAS_PERMISSIBLE_VALUE edges
    ▼
LadybugDB graph
```

### Running it

```bash
# Ingest one schema for real
python neuro_ghost/ingest_linkml.py --file registry_schemas/bbqs.yml

# Preview without writing anything
python neuro_ghost/ingest_linkml.py --file registry_schemas/bbqs.yml --dry-run

# Preview *and* print every RegistryClass/RegistryProperty/RegistryValueSet/
# ProvenanceEntry that would be created, in full (id, sha256_hash, all
# fields, id-references resolved back to human-readable names)
python neuro_ghost/ingest_linkml.py --file registry_schemas/bbqs.yml --dry-run --verbose
```

`--verbose` works without `--dry-run` too — it uses the real DB connection
for its dedup lookup, so the ids it prints match what actually gets written
right after. Other flags: `--wipe` (remove this source's attestations before
re-ingesting), `--registry-version`, `--issue`, `--agent`. Omit `--file` to
ingest every `.yml` in `registry_schemas/`.

### 1. `parse_linkml()` (`neuro_ghost/ingest_linkml.py`)

Loads the YAML via `linkml_runtime`'s `SchemaView`, not a hand-rolled YAML
walk. This matters because `SchemaView.class_induced_slots()` resolves real
LinkML semantics — a class's *effective* slot list includes everything
inherited via `is_a` or `mixins`, and everything declared inline as
`attributes:` — before ingestion ever sees the data. A class that declares no
slots of its own but has `is_a: Device` still gets `Device`'s slots.

Output is a plain dict: `{"meta": {...}, "classes": {name: {iri, definition,
is_a, is_abstract, slots}}, "slots": {name: {iri, definition, value_range
(a list — a union has several), units, multivalued, required, pattern}}}`.

### 2. `build_registry_entities()`

Converts the dict into real, id-identified objects with content
fingerprints and provenance references:

- **Properties are built first.** For each one:
  1. Compute `sha256_hash` from the `HashSubset` fields —
     `name`/`description`/`concept_uri` — via `compute_content_hash_for()`.
     A property is a *pure concept*: its value type and unit are **not** part
     of its identity (they're not fields on it at all — they live on rules,
     see below), and `aliases` is excluded too (see the "Data model" table).
  2. Look up any existing entity in the graph with that `sha256_hash`
     (`find_id_by_sha256(conn, "RegistryProperty", sha)`). If found, reuse
     that row's `id`; otherwise mint a fresh `uuid4`.
  3. Construct a `ProvenanceEntry` for this attestation and store it in a
     `provenance_entries: dict[str, ProvenanceEntry]` collection; pass its
     `id` on the property's `provenance` list.
- **Classes reference their properties by id (UUID)**, sorted, in the
  `properties` slot. This is why a class's own `sha256_hash` depends on its
  full induced property set — two classes with the same properties
  (regardless of declaration order) hash the same. Dedup on `sha256_hash`
  then also collapses the class row itself.
- **`is_a` is resolved recursively to the parent's id**, not its name — so
  multi-level hierarchies resolve correctly regardless of the order classes
  appear in the file. A schema that parses at all is guaranteed to have every
  `is_a` target resolvable within its own import closure (that's
  `SchemaView`'s job), so this recursion always terminates cleanly.
- **Every entity gets one `ProvenanceEntry` per ingestion** — the entry
  itself is not embedded on the entity; the meta_model's `provenance` slot
  is `inlined: false`, storing only `ProvenanceEntry.id` references.
  Provenance objects live in the returned `provenance_entries` dict.
  Fields: `had_primary_source` (a real FK to the SchemaSource that attested
  to it), `was_attributed_to` (agent), `generated_at_time`,
  `was_generated_by`, `registry_version`. Field names mirror PROV-O terms
  directly (`prov:hadPrimarySource`, `prov:wasAttributedTo`,
  `prov:generatedAtTime`, `prov:wasGeneratedBy`).

- **Rules are built last**, after properties, classes, and enums all have
  ids. Each declarative facet a slot states becomes one atomic `RegistryRule`
  (`applies_to` the property): `REQUIRED`/`PATTERN`/`MIN_VALUE`/`MAX_VALUE`
  from the constraints, a `RANGE` rule per permitted value type (a union is
  simply several RANGE rules), and a `UNIT` rule for the unit. Because ranges
  live on rules built *after* the classes/enums they point at, a `RANGE`
  rule's `rule_value` is the target's real id directly — no second pass — and
  a self-referential range (e.g. `ProvEntity.was_derived_from -> ProvEntity`)
  is cycle-free, since the class hash never depended on the range.

Return signature is a 6-tuple: `(properties, registry_classes, value_sets,
permissible_values, rules, provenance_entries)`. The caller — `insert_schema` —
threads `provenance_entries` through to the writers.

### 3. `write_registry_entities()` + `write_structural_edges()` (`neuro_ghost/db.py`)

For each entity: does a node with this `id` already exist? (The `id` was
already reused during build via a `sha256_hash` lookup, so a match here
means the same content, seen before.)
- **No** → create it.
- **Either way** → attach this ingestion's `ProvenanceEntry` (looked up in
  `provenance_entries` by the id on the entity's `provenance` list),
  *unless this exact source already has one on that node* (idempotent
  re-ingestion: running the same file from the same source twice adds
  nothing the second time).

Then `HAS_PROPERTY` and `SUBCLASS_OF` edges get created from the resolved
UUID references. These functions are shared between `ingest_linkml.py` and
`seed.py` — schema.org is ingested through the exact same path, just with
`source="schema.org"`.

## External imports

A submitted schema can `imports:` other LinkML schemas by name. SchemaView
resolves those names by looking in the input file's own directory, so any
name that isn't a CURIE-form built-in (`linkml:types`, `biolink:core`) needs
the sibling file on disk. NeuroGhost stores each submission as a single
`registry_schemas/<name>.yml` file, so schemas built on shared upstream
models (biolink, PROV, …) would otherwise arrive with their imports
unresolved — SchemaView's `class_induced_slots()` then raises
`No such class` on the missing parent, `parse_linkml`'s tolerant branch
silently strips the `is_a` link, and every inherited slot is lost.

`neuro_ghost/import_resolver.py` fixes that. A submitter declares where
the missing siblings live via a LinkML `annotations:` entry — LinkML-native,
so no new file format:

```yaml
id: https://identifiers.org/brain-bican/genome-annotation-schema
imports:
  - linkml:types      # built-in, resolved by SchemaView
  - bican_biolink     # external, fetched by the resolver
  - bican_core        # external, fetched by the resolver
annotations:
  imports_source: https://raw.githubusercontent.com/brain-bican/models/main/linkml-schema
```

At parse time, `parse_linkml()` runs the resolver first:

1. Reads `annotations.imports_source` from the input schema.
2. Copies the input into a per-invocation `tempfile.TemporaryDirectory()`.
3. For each non-CURIE name in `imports:`, checks whether the sibling
   already sits next to the input schema (submitters can still commit
   the whole family). If not, fetches `<imports_source>/<name>.yaml`
   (fallback `.yml`) into the temp dir.
4. Recurses into each fetched file — its own `imports:` are resolved the
   same way, inheriting the parent's `imports_source` unless the child
   declares its own. A `seen` set breaks cycles; a `MAX_DEPTH` cap
   prevents runaway.
5. Hands SchemaView the path to the temp-dir copy of the input schema,
   with every resolvable sibling now next to it.

If a schema has no external imports (only CURIE built-ins, or none at
all), the resolver is a no-op — `parse_linkml()` sees the original path
and no temp dir writes happen. Existing schemas (bbqs, bids, dandi, …)
go through unchanged.

An import name with no `imports_source` to fetch from — and no local
sibling next to the input — raises `FileNotFoundError` at parse time.
That's deliberate: silent parse degradation (dropping `is_a` chains and
their inherited slots) is worse than a loud error at ingest.

## The data model

See [`model.md`](model.md) for a diagram of every class and relationship
in `meta_model.yaml`.

| Field | On | Notes |
|---|---|---|
| `id` | every registered object (`RegistryEntity` subclasses **and** `ProvenanceEntry`/`SchemaSource`/`SchemaVersionSnapshot`/`Mapping`/`RegistrySchema`/`Transform`) | UUID (`uuid4`) minted at first ingest, uniform across all classes. Primary key for every FK. |
| `sha256_hash` | every `RegistryEntity` (`RegistryClass`/`RegistryProperty`/`RegistryValueSet`/`PermissibleValue`/`RegistryRule`) | Content fingerprint over `HashSubset`-marked fields. Not the identifier — drives cross-source dedup by letting a second ingest of the same content reuse the existing `id` rather than mint a new UUID. |
| `name`, `description` | `RegistryClass`, `RegistryProperty` (via `RegistryEntity`) | Identity-defining (part of the hash). |
| value type, unit | `RegistryRule` (not `RegistryProperty`) | A property's value type and unit are **not** part of its identity — they aren't fields on `RegistryProperty` at all. A property is a pure concept (name + description), so the same concept collapses across schemas even when one types it `integer` and another `string`, or one measures it in years and another in months. Each realization is recorded as its own `RegistryRule`: `rule_type=RANGE` (`rule_value` = XSD CURIE / class `id` / value-set `id`; a union is simply several RANGE rules, one per permitted type) or `UNIT` (`rule_value` = UCUM code). Alignment reads datatype/unit compatibility off these rules. |
| `properties`, `parent_class`, `class_mixins` | `RegistryClass` | `HashSubset`-defining, stored as UUID `id` references (not embedded). Two classes with the same content (same property ids, same parent id) collapse via `sha256_hash` dedup. |
| `is_abstract`, `is_mixin` | `RegistryClass` | LinkML's `abstract`/`mixin` flags. Both `HashSubset`-defining (they change what a class *is*) — an abstract class and a concrete one with otherwise identical content are different concepts. Default to `false` via `ifabsent`. |
| `class_uri` / `slot_uri` (`concept_uri`) | `RegistryClass` / `RegistryProperty` | Ontology IRI preserved from the source. Part of `HashSubset` on `RegistryEntity` — sources declaring the same content under the same `concept_uri` collapse cleanly; if they declare it under different IRIs, they land as separate entities (a deliberate conservative choice — treating differing IRIs as accidental collisions would overstate similarity). |
| `aliases` | `RegistryEntity` | Alternate names/synonyms (`skos:altLabel`), feeding `align.py`'s `alias_overlap` signal. **Not** part of the hash — different sources may supply different aliases for the same content. |
| `provenance` | every `RegistryEntity` | List of `ProvenanceEntry.id` references (**not** embedded objects — the meta_model uses `inlined: false` here, matching the graph, which stores `ProvenanceEntry` as a separate node linked via `HAS_PROVENANCE` / `HAS_PROVENANCE_P`). Accumulates, never affects `id` or `sha256_hash`. |
| `skos_mappings` | every `RegistryEntity` | List of `Mapping.id` references (also `inlined: false`, same reasoning as `provenance`). Empty for every real ingested schema today; no writer emits mappings yet. |
| `had_primary_source`, `attests_to`, `was_attributed_to`, `generated_at_time`, `was_generated_by`, `was_derived_from`, `registry_version`, `source_version` | `ProvenanceEntry` | Field names mirror PROV-O terms directly (`prov:hadPrimarySource`, `prov:wasAttributedTo`, `prov:generatedAtTime`, `prov:wasGeneratedBy`, `prov:wasDerivedFrom`). `had_primary_source` is a real FK to the attesting `SchemaSource` (by its UUID `id`), not a denormalized label. `attests_to` is the reverse of `RegistryEntity.provenance`, carrying the referenced entity's `id`. `registry_version` has no PROV-O term — a purely registry-specific extension. It lives here, not on the entity — the same entity can be attested by different sources at different times, each under a different registry version, so a single scalar on the entity doesn't fit. |
| `id`, `source_id`, `label`, `title`, ... | `SchemaSource` | `id` is the registry's internal UUID (stable graph handle for FKs). `source_id` is the persistent IRI the source schema declared as its own `id:` — kept distinct from `id` so re-ingestion under a different registry UUID (or across registries) still resolves to the same source-of-truth identifier. `SchemaSource` is deliberately just a **provenance record** — a stable label to attribute registry entities to. Schema-shape metadata (`default_range`, `namespace_iri`, `imports`) lives on `RegistrySchema` for the compose-and-export flow, not here. |

Field names were deliberately aligned with LinkML's own metamodel
(`description`, `range`, `class_uri`/`slot_uri`, `is_a`, `abstract`) rather
than inventing parallel terminology — e.g. `parse_linkml()` already produces
`is_a` straight from `SchemaView`, so there's no translation step.

**Deliberately not modeled yet:** `required`/`multivalued` used to live on
`RegistryProperty` directly, which meant a property required in one schema's
usage and optional in another's could never share a hash. They've been
removed entirely — that's a **`RegistryRule`** concern (still a stub), not identity.

## Alignment

`neuro_ghost/align.py` runs *after* ingestion, writing `ALIGNED_TO` edges
between already-distinct `id`s. It never merges identities — that's
deliberate for now. Content-hashing already handles "these are
byte-for-byte the same"; alignment's job is "these are *related* but not
identical" (`age_years` vs `age_at_scan`), which needs real similarity
judgment. Until that's built out, ordering it after commit (not before, the
way some richer designs do) is the correct choice — there's nothing yet
that could inform the hash before commit anyway.

Currently `align.py` is a **minimal placeholder** (exact `class_uri`
matches only) — the real, multi-signal alignment work is meant to come
from an external package, Proteus's own `proteus-align`
(github.com/neurovium/Proteus). See `align.py`'s own module docstring
before extending it; the intent is that this file changes only if the
`ALIGNED_TO` edge shape itself changes, not every time the meta-model does.

## Testing: two layers, don't conflate them

`tests/test_ingest_linkml.py` tests two distinct steps against the same
fixture (`tests/fixtures/comprehensive.yml`, which packs a mixin, an
abstract base, `is_a` inheritance, both `slots:` and inline `attributes:`,
prefix resolution from both the schema's own `prefixes:` and the built-in
fallback map, `multivalued`/`required`/`pattern`, and a units-in-description
extraction into one schema) — and it matters which one a given assertion is
about:

- **`parse_linkml()`'s intermediate dict** legitimately has `multivalued`/
  `required`/`pattern` — that's a raw, general-purpose extraction of what the
  LinkML slot declares, independent of what the registry keeps.
- **`build_registry_entities()`'s output** (`RegistryProperty`/`RegistryClass`)
  does **not** have those fields at all — `RegistryProperty.model_fields`
  doesn't even define them. The test asserts along two axes:
  * **Property `sha256_hash` values are asserted exactly** — deterministic
    across runs since the fingerprint is a pure content hash of the
    property's own fields.
  * **`id` values are asserted structurally** (parse as `uuid.UUID`) and by
    **cross-reference consistency** (a class's `parent_class` equals the
    parent's `id`; `properties` list equals the target properties' `id`s).
    Class `sha256_hash` values include property UUIDs, so they only become
    deterministic when property ids stabilize via dedup — see
    `test_class_hash_dedup_makes_a_re_ingest_deterministic`, which
    monkeypatches `find_id_by_sha256` to prove that a second ingest reuses
    the first's ids and produces identical hashes.

Saying "parse_linkml extracts X" and "the registry stores X" are different
claims — test each layer for what it actually is, not for what you assume
the other layer does with it.

`tests/test_ingest_registry.py::test_required_does_not_affect_property_identity`
takes this one step further, end to end: two schemas declare the exact same
`age` slot except one marks it `required: true`. Ingesting both must produce
exactly one `RegistryProperty` node, not two — proving `required` doesn't
leak into identity, in the real graph, not just in an isolated object.

## Open question: when should ProvenanceEntry.registry_version be set?

The whole-registry version (the semver in `data/registry.json`, e.g. `1.7.0`)
only gets computed once, at the very end of a submission, when
`export_json.py` reads the last entry in `data/provenance.json` and bumps it.
`seed.py`/`ingest_linkml.py`/`align.py` all run *before* that — so the version
an entity is actually going to belong to doesn't exist yet at the moment it's
ingested.

That rules out the obvious fix ("pass the current, pre-bump version to
ingest_linkml.py/align.py") — it would record the version this submission is
replacing, not the one it's part of. The consistent fix would be computing
the bump once, up front (alongside where the Action already determines
`bump` type in "Parse issue metadata"), and threading that single value
through every step including `export_json.py` — instead of `export_json.py`
computing it independently after the fact.

**Not implemented.** `schema_submission.yml` does not pass `--registry-version`
to `ingest_linkml.py` or `align.py` — those entities' `ProvenanceEntry.
registry_version` stays `None` for now, pending a decision on the above.

## Known gaps (as of this writing)

- **`index.html`** (frontend) still reads `data/registry.json` — the field
  names now include `id` (UUID) and `sha256_hash` on every entity, and
  alignment cross-refs use `target_id`. The Graph Schema page's ER diagram
  has been updated to show the new fields; runtime lookups are being
  updated too, but a proper UI pass is still owed.
- **`was_derived_from`** on `ProvenanceEntry` is never populated — nothing yet
  detects "this hash supersedes that one" (would need an anchor like
  `(name, source)` to correlate an edit against prior content).
- **`RegistryRule` is populated for the common facets.**
  `build_registry_entities()` constructs rules for `REQUIRED`/`PATTERN`/
  `MIN_VALUE`/`MAX_VALUE`, plus a `RANGE` rule per permitted value type
  (a union is several RANGE rules) and a `UNIT` rule for the unit. Not yet
  wired: the remaining `rule_type`s (`MIN_LENGTH`/`MAX_LENGTH`/
  `ENUM_MEMBERSHIP`/`FORMAT`/`EXPRESSION_*`) and per-class refinements
  (`used_in_class` is always unset — every rule is schema-level for now).
  `Transform` is still a genuine stub (`id`/`name`/`description` only).
- **`SemanticIdentity`/`PRIOR_VERSION*`** tables in `db.py`'s DDL are dead
  (superseded by content-hash identity) but not yet removed.
- **`pandas`** isn't in `requirements.txt`, so `align.py`'s embedding cache
  silently no-ops (pre-existing gap).
- **`aliases` and unit aren't populated by any real source schema yet.**
  `ingest_linkml.py` extracts what it can (regex'd free text into a `UNIT`
  rule's `rule_value`), but none of the six real ingested schemas
  (aind/bbqs/bids/dandi/nwb/openminds) declare LinkML's own `aliases:`/
  `unit:` constructs — so aliases stay largely empty and UNIT rules are rare
  until source schemas adopt them, or a text-mining step is built.
- **`scripts/update_graph.py`'s diagram may still draw a `UnitOfMeasure`
  node.** That class was removed when unit moved to a `UNIT` `RegistryRule`;
  the diagram script should be re-synced so it no longer shows it.
