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
`description`, `range`, and `units` get the **same** `hash_id`, regardless of
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
              ├── ProvenanceEntry{source: "schema_a", ...}
              └── ProvenanceEntry{source: "schema_b", ...}
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
RegistryProperty / RegistryClass / Rule instances (Pydantic, hash_id already set)
    │  write_registry_entities()  — write-if-new, attach-provenance-if-new
    │  write_structural_edges()   — HAS_PROPERTY, SUBCLASS_OF
    │  _write_rules()             — APPLIES_TO_P
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
  `name`/`description`/`range`/`units` only — `slot_uri` is stored on the
  object but excluded from the hash (it's origin metadata, not identity).
- **Classes reference their properties by hash_id**, sorted. This is why a
  class's own hash depends on its full induced property set — two classes
  with the same properties (regardless of declaration order) hash the same.
- **`is_a` is resolved recursively to the parent's hash_id**, not its name —
  so multi-level hierarchies resolve correctly regardless of the order
  classes appear in the file. A schema that parses at all is guaranteed to
  have every `is_a` target resolvable within its own import closure (that's
  `SchemaView`'s job), so this recursion always terminates cleanly.
- **Every entity gets one `ProvenanceEntry`** for this ingestion — `source`,
  `attributed_to` (agent), `generated_at`, `activity`, `registry_version` —
  entirely separate from the hash computation.
- **A property that declares `required`/`multivalued`/`pattern`/min/max also
  gets a `Rule`**, `applies_to` = that property's `hash_id`. A plain property
  with none of these gets no `Rule` at all — see [Rule](#rule-usage-constraints-as-their-own-entity)
  below.

### 3. `write_registry_entities()` + `write_structural_edges()` + `_write_rules()` (`neuro_ghost/db.py`, `neuro_ghost/ingest_linkml.py`)

For each entity: does a node with this `hash_id` already exist?
- **No** → create it.
- **Either way** → attach this ingestion's `ProvenanceEntry`, *unless this
  exact source already has one on that node* (idempotent re-ingestion: running
  the same file from the same source twice adds nothing the second time).

Then `HAS_PROPERTY` and `SUBCLASS_OF` edges get created from the resolved
hash references, and `APPLIES_TO_P` from each `Rule` to the property it
constrains. The first two are shared between `ingest_linkml.py` and
`seed.py` — schema.org is ingested through the exact same path, just with
`source="schema.org"` (though `seed.py` never builds any `Rule`s — schema.org's
base vocabulary doesn't declare `required`/`multivalued`/etc. on its slots).

## The data model

| Field | On | Notes |
|---|---|---|
| `hash_id` | every entity | Content-derived. `RegistryClass`/`RegistryProperty` only — `ProvenanceEntry` uses a random `uid` instead, since it's a per-attestation record, not a deduplicated concept. |
| `name`, `description` | `RegistryClass`, `RegistryProperty` | Identity-defining (part of the hash). |
| `range`, `units` | `RegistryProperty` | Identity-defining. |
| `properties`, `is_a`, `mixins` | `RegistryClass` | Identity-defining — all stored as hash_id references. |
| `class_uri` / `slot_uri` | `RegistryClass` / `RegistryProperty` | Ontology IRI preserved from the source. **Not** part of the hash — two schemas using different IRIs (or none) for the same content still collapse to one node. |
| `provenance` | both | List of `ProvenanceEntry`. Accumulates, never affects `hash_id`. |
| `source`, `attributed_to`, `generated_at`, `activity`, `derived_from`, `registry_version` | `ProvenanceEntry` | PROV-O–grounded (`slot_uri: prov:wasAttributedTo` etc.). `registry_version` lives here, not on the entity — the same entity can be attested by different sources at different times, each under a different registry version, so a single scalar on the entity doesn't fit (same reasoning as dropping `source_label`). |
| `applies_to`, `required`, `multivalued`, `pattern`, `minimum_value`, `maximum_value`, `function_body` | `Rule` | Identity-defining — see [Rule](#rule-usage-constraints-as-their-own-entity). |

Field names were deliberately aligned with LinkML's own metamodel
(`description`, `range`, `class_uri`/`slot_uri`, `is_a`, `abstract`) rather
than inventing parallel terminology — e.g. `parse_linkml()` already produces
`is_a` straight from `SchemaView`, so there's no translation step.

## Rule: usage constraints as their own entity

`required`/`multivalued` used to live on `RegistryProperty` directly, which
meant a property required in one schema's usage and optional in another's
could never share a `hash_id`. They're not modeled on `RegistryProperty` at
all now — a `Rule` is a separate content-addressed entity that references
the property it constrains:

```
RegistryProperty "age"  (hash_id = A)
        ▲
        │ APPLIES_TO_P
        │
Rule { applies_to: A, required: true }  (hash_id = B)
        ├── ProvenanceEntry{source: "bids", ...}
        └── ProvenanceEntry{source: "dandi", ...}
```

- `applies_to` (the constrained property's `hash_id`) **is** part of the
  `Rule`'s own hash — identical constraints on two *different* properties
  are different rules, by design.
- Same collapsing behavior as everything else: two sources declaring the
  exact same constraints on the exact same property produce one `Rule` node
  with two `ProvenanceEntry` records, not two `Rule`s
  (`test_identical_rule_from_two_sources_shares_one_hash_id`).
- A property with none of `required`/`multivalued`/`pattern`/min/max gets no
  `Rule` at all — `build_registry_entities()`'s `_has_constraints()` gate
  keeps unconstrained properties from accumulating empty, meaningless rules.
- Scoped to `RegistryProperty` only for now (`applies_to: range: RegistryProperty`
  in the meta-model) — class-level rules are a possible future extension,
  not built. (A pre-existing, still-unused `APPLIES_TO` edge from `Rule` to
  `RegistryClass` predates this and is a leftover placeholder for that.)
- `required`/`multivalued` default to `false` rather than `null`
  (`ifabsent: 'false'` in the meta-model) for the same reason `RegistryClass.abstract`
  does: they're identity-defining, so a `null` would hash differently from an
  explicit `false` and silently produce a second `Rule` for the same content.
- Written through the same `entity_exists()`/`create_entity_node()`/
  `write_provenance()` functions as `RegistryClass`/`RegistryProperty`/`ValueSet`
  (`_write_rules()` in `ingest_linkml.py`, following the same pattern as
  `_write_value_sets()`) — no separate code path.

**`function_body`**: for constraints the declarative fields can't express
(cross-field or business-logic validation), `Rule` also has a `function_body`
slot holding Python source as plain text — same treatment as `pattern`, not a
compiled/pickled/imported callable, so `Rule`'s identity stays a plain content
hash with no dependency on code existing elsewhere. `parse_linkml()`/
`build_registry_entities()` never sets it (LinkML schemas don't carry
executable Python) — it's for `Rule`s built some other way, e.g. manually or
by a future authoring tool (`test_rule_can_hold_a_python_function_body`).
Nothing in this codebase executes it yet; this only adds the ability to
save it.

## Alignment

`neuro_ghost/align.py` runs *after* ingestion, computing a similarity score
(IRI exact-match + embedding-based name/description similarity) between
already-distinct `hash_id`s and writing `ALIGNED_TO` edges. It never merges
identities — that's deliberate for now. Content-hashing already handles
"these are byte-for-byte the same"; alignment's job is "these are *related*
but not identical" (`age_years` vs `age_at_scan`), which needs real
similarity judgment. Until that's built out, ordering it after commit (not
before, the way some richer designs do) is the correct choice — there's
nothing yet that could inform the hash before commit anyway.

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
leak into identity, in the real graph, not just in an isolated object. The
same test also confirms where `required: true` *does* end up: one `Rule`,
`APPLIES_TO_P` the "age" property.
`test_identical_rule_from_two_sources_shares_one_hash_id` proves the
content-addressing guarantee applies to `Rule` itself, the same way it does
to `RegistryProperty`/`RegistryClass`.

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

- **`derived_from`** on `ProvenanceEntry` is never populated — nothing yet
  detects "this hash supersedes that one" (would need an anchor like
  `(name, source)` to correlate an edit against prior content).
- **`Transform`** is still a stub (`hash_id`/`name`/`description` only) —
  `Rule` and `ValueSet` are real now (see above).
- **`SemanticIdentity`/`PRIOR_VERSION*`** tables in `db.py`'s DDL are dead
  (superseded by content-hash identity) but not yet removed.
- **`pandas`** isn't in `requirements.txt`, so `align.py`'s embedding cache
  silently no-ops (pre-existing gap).
- **New `Rule`s/`ValueSet`s don't count toward `has_new_content`** in
  `insert_schema()` — that check only looks at `classes_new`/`properties_new`,
  so a re-ingestion whose *only* change is a new constraint or a new enum
  value produces no `SchemaVersionSnapshot` bump. Pre-existing for `ValueSet`;
  `Rule` inherits the same gap rather than fixing it in passing.
