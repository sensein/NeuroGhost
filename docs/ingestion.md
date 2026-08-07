# How schema ingestion works

> **Status: living document.** This describes the registry as of the
> `ref/linkml_ingestion` rework (content-addressed identity). It will be
> updated as ingestion continues to change — treat it as the current source
> of truth, not a historical record.

## The problem this solves

Every neuroscience data standard (BIDS, NWB, DANDI, openMINDS, AIND, ...)
defines its own vocabulary. The same concept — "age", "subject", "device
manufacturer" — gets redefined independently in each one, usually under a
different name, attached to a different class. The registry's job is to
notice when two things from different schemas are actually the same concept,
without a human manually saying so for every pair.

The previous design gave every ingested class/property a random,
UUID-derived `hash_id` and tracked "is this the same as before" by looking
up `(iri, source_label)` and diffing fields by hand. That only ever compared
a schema against *its own* prior ingestions — it had no way to notice that
two *different* schemas defined the same thing.

## The core idea: content-addressed identity

A `RegistryClass`/`RegistryProperty`'s `hash_id` is now a SHA-256 hash of its
own content — nothing else. Two properties with the same `name`,
`description`, `range`, and `unit` get the **same** `hash_id`, regardless of
which schema they came from, what it's called there, or when it was
ingested. Identity is separate from provenance: instead of creating a second
node for a second source, the *existing* node gets a second `ProvenanceEntry`
recording that this source also attests to it.

```
schema_a.yml: Subject.age  (name=age, description=..., range=integer)
schema_b.yml: Participant.age  (same content, different class)
                    │
                    ▼
        ONE RegistryProperty node (hash_id = hash of the content)
              ├── ProvenanceEntry{had_primary_source: SchemaSource("schema_a"), ...}
              └── ProvenanceEntry{had_primary_source: SchemaSource("schema_b"), ...}
```

No alignment step, no manual annotation — pure hash equality gives you this
for free. (Real alignment — noticing that *differently*-named/described
concepts are related — is a separate, deliberately basic step for now; see
[Alignment](#alignment) below.)

## The pipeline

```
LinkML YAML
    │  parse_linkml()          — SchemaView-based parsing
    ▼
intermediate dict            {classes: {...}, slots: {...}}
    │  build_registry_entities()  — compute content hashes
    ▼
RegistryProperty / RegistryClass instances (Pydantic, hash_id already set)
    │  write_registry_entities()  — write-if-new, attach-provenance-if-new
    │  write_structural_edges()   — HAS_PROPERTY, SUBCLASS_OF
    ▼
LadybugDB graph
```

### 1. `parse_linkml()` (`neuro_ghost/ingest_linkml.py`)

Loads the YAML via `linkml_runtime`'s `SchemaView`, not a hand-rolled YAML
walk. This matters because `SchemaView.class_induced_slots()` resolves real
LinkML semantics — a class's *effective* slot list includes everything
inherited via `is_a` or `mixins`, and everything declared inline as
`attributes:` — before ingestion ever sees the data. A class that declares no
slots of its own but has `is_a: Device` still gets `Device`'s slots.

Output is a plain dict: `{"meta": {...}, "classes": {name: {iri, definition,
is_a, is_abstract, slots}}, "slots": {name: {iri, definition, value_range,
units, multivalued, required, pattern}}}`.

### 2. `build_registry_entities()`

Converts the dict into real, hash-identified objects:

- **Properties are built first.** Each one's `hash_id` is computed from
  `name`/`description`/`range`/`unit` only — `slot_uri` is stored on the
  object but excluded from the hash (it's origin metadata, not identity).
- **Classes reference their properties by hash_id**, sorted. This is why a
  class's own hash depends on its full induced property set — two classes
  with the same properties (regardless of declaration order) hash the same.
- **`is_a` is resolved recursively to the parent's hash_id**, not its name —
  so multi-level hierarchies resolve correctly regardless of the order
  classes appear in the file. A schema that parses at all is guaranteed to
  have every `is_a` target resolvable within its own import closure (that's
  `SchemaView`'s job), so this recursion always terminates cleanly.
- **Every entity gets one `ProvenanceEntry`** for this ingestion —
  `had_primary_source` (a real FK to the SchemaSource that attested to it,
  not a denormalized label), `was_attributed_to` (agent), `generated_at_time`,
  `was_generated_by`, `registry_version` — entirely separate from the hash
  computation. Field names mirror PROV-O terms directly (`prov:hadPrimarySource`,
  `prov:wasAttributedTo`, `prov:generatedAtTime`, `prov:wasGeneratedBy`).

### 3. `write_registry_entities()` + `write_structural_edges()` (`neuro_ghost/db.py`)

For each entity: does a node with this `hash_id` already exist?
- **No** → create it.
- **Either way** → attach this ingestion's `ProvenanceEntry`, *unless this
  exact source already has one on that node* (idempotent re-ingestion: running
  the same file from the same source twice adds nothing the second time).

Then `HAS_PROPERTY` and `SUBCLASS_OF` edges get created from the resolved
hash references. These two functions are shared between `ingest_linkml.py`
and `seed.py` — schema.org is ingested through the exact same path, just with
`source="schema.org"`.

## The data model

See [`model.md`](model.md) for a diagram of every class and relationship
in `schemas/meta_model.yaml`.

| Field | On | Notes |
|---|---|---|
| `hash_id` | every `RegistryEntity` (`RegistryClass`/`RegistryProperty`/`ValueSet`/`PermissibleValue`/...) | Content-derived. Everything else (`ProvenanceEntry`, `SchemaSource`, `SchemaVersionSnapshot`, `Mapping`) uses a plain random `id` instead, since it isn't a deduplicated, content-addressed concept — a per-attestation record or a mutable administrative record. |
| `name`, `description` | `RegistryClass`, `RegistryProperty` | Identity-defining (part of the hash). |
| `range`, `unit` | `RegistryProperty` | Identity-defining. `unit` is a structured `UnitOfMeasure` (`ucum_code`, `has_quantity_kind`, `symbol`, `abbreviation`, `descriptive_name`), inlined onto `RegistryProperty`'s own node — not its own content-addressed entity. |
| `properties`, `is_a`, `mixins` | `RegistryClass` | Identity-defining — all stored as hash_id references. |
| `class_uri` / `slot_uri` | `RegistryClass` / `RegistryProperty` | Ontology IRI preserved from the source. **Not** part of the hash — two schemas using different IRIs (or none) for the same content still collapse to one node. |
| `aliases` | `RegistryEntity` | Alternate names/synonyms (`skos:altLabel`), feeding `align.py`'s `alias_overlap` signal. **Not** part of the hash — like `class_uri`/`slot_uri`, different sources may supply different aliases for the same content. |
| `provenance` | both | List of `ProvenanceEntry`. Accumulates, never affects `hash_id`. |
| `had_primary_source`, `was_attributed_to`, `generated_at_time`, `was_generated_by`, `was_derived_from`, `registry_version` | `ProvenanceEntry` | Field names mirror PROV-O terms directly (`prov:hadPrimarySource`, `prov:wasAttributedTo`, `prov:generatedAtTime`, `prov:wasGeneratedBy`, `prov:wasDerivedFrom`). `had_primary_source` is a real FK to the attesting `SchemaSource`, not a denormalized label. `registry_version` and `source_description` have no PROV-O term — purely registry-specific extensions. `registry_version` lives here, not on the entity — the same entity can be attested by different sources at different times, each under a different registry version, so a single scalar on the entity doesn't fit. |

Field names were deliberately aligned with LinkML's own metamodel
(`description`, `range`, `class_uri`/`slot_uri`, `is_a`, `abstract`) rather
than inventing parallel terminology — e.g. `parse_linkml()` already produces
`is_a` straight from `SchemaView`, so there's no translation step.

**Deliberately not modeled yet:** `required`/`multivalued` used to live on
`RegistryProperty` directly, which meant a property required in one schema's
usage and optional in another's could never share a hash. They've been
removed entirely — that's a **`Rule`** concern (still a stub), not identity.

## Alignment

`neuro_ghost/align.py` runs *after* ingestion, writing `ALIGNED_TO` edges
between already-distinct `hash_id`s. It never merges identities — that's
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
  doesn't even define them. Since `hash_id` is a pure content hash (no
  randomness), this layer's test hardcodes the exact expected hash strings —
  reproducible on any machine, and any change to the hash computation, the
  fields carried into the model, or the `is_a`/`properties` resolution shows
  up as a failure here.

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

- **`index.html`** (frontend) still expects the pre-rework JSON shape
  (`source` singular; `multivalued`/`required` on properties). A minimal
  compat patch was written and then deliberately reverted — not worth fixing
  until a proper UI pass.
- **`was_derived_from`** on `ProvenanceEntry` is never populated — nothing yet
  detects "this hash supersedes that one" (would need an anchor like
  `(name, source)` to correlate an edit against prior content).
- **`Rule`/`Transform`** are still stubs (`hash_id`/`name`/`description`
  only) — `ValueSet` and `PermissibleValue` are real now.
- **`SemanticIdentity`/`PRIOR_VERSION*`** tables in `db.py`'s DDL are dead
  (superseded by content-hash identity) but not yet removed.
- **`pandas`** isn't in `requirements.txt`, so `align.py`'s embedding cache
  silently no-ops (pre-existing gap).
- **`aliases` and `unit` aren't populated by any real source schema yet.**
  `ingest_linkml.py` extracts what it can (regex'd free text into
  `unit.ucum_code`), but none of the six real ingested schemas
  (aind/bbqs/bids/dandi/nwb/openminds) declare LinkML's own `aliases:`/
  `unit:` constructs — so both fields stay largely empty until source
  schemas adopt them, or a text-mining step is built.
- **`scripts/update_graph.py`'s diagram draws `RegistryProperty --HAS_UNIT-->
  UnitOfMeasure`** as if it were a separate node/edge — it isn't; `unit` is
  `db_inline: true` and flattens onto `RegistryProperty`'s own columns (see
  `_build_registry_ddl()`). The diagram script doesn't special-case
  `db_inline` the way the real DDL generator does.
