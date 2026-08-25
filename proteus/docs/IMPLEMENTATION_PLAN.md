# Implementation Plan — proteus

The build order from `alignment_pipeline_design_v2.md`, turned into milestones
with acceptance criteria. The ordering principle: every stage after Stage 1 is
only as good as the labels the curation loop feeds it, and the loop has the
longest lead time (humans). So the vertical slice comes first, and the anchor
channel jumps ahead of embeddings because it is the cheapest high-precision
signal and shortens that lead time.

**Assumed to exist upstream:** ingestion, the registry, and a graph built from
it. This repo talks to them only through `RegistryAdapter`
(`interfaces.py`); `adapters/mock_registry.py` + YAML fixtures stand in until
the real adapter is written.

---

## Milestone 1 — Vertical slice  ✅ (implemented in this skeleton)

Blocking + lexical/unit signals + SSSOM output, end to end.

**Scope**
- Stage 0: profiles from registry entities (no anchor enrichment yet; anchors
  are carried through but not resolved).
- Stage 1: lexical blocking channel + unit veto (embedding and anchor channels
  return empty; interfaces in place).
- Stage 2: lexical signals (normalized-name similarity, token Jaccard,
  alias overlap) + unit compatibility feature. Other signals emit
  `MISSING`.
- Stage 3: fixed-weight combination, uncalibrated (labeled as such in output).
- Stage 4: threshold rules; statistical evidence caps at `CLOSE_MATCH`
  (invariant 10 — the anchor pathway to EXACT arrives in M2).
- Stage 5: pass-through with a cardinality sanity check stub.
- Stage 6: SSSOM TSV MappingSet, `review_status=PROPOSED`, per-signal
  provenance in `comment`.

**Acceptance**
- `python -m proteus.pipeline <schema_a> <schema_b> out.tsv` produces a
  valid SSSOM TSV on the two toy cosmology fixtures.
- `redshift` × `z_spec`-style pairs surface; the `wavelength[m]` ×
  `exposure_time[s]` pair is vetoed and appears in the veto log.
- `pytest` green.
- **Exit ramp:** hand the output to a curator; target ≥50 curated mappings
  before starting M3 (M2 does not need labels).

## Milestone 2 — Anchor channel & declared semantics

Earlier than embeddings, per the v2 build order.

**Scope**
- Ontology resolution + caching; `ReasonerBackend` implemented with ELK (via
  ROBOT or owlapi bridge); materialized anchor index per ontology version.
- Stage 0 anchor enrichment: referenced term's label/synonyms/definition into
  a separate `anchor_text` profile field (never concatenated into `name`).
- Stage 1 anchor channel: candidate injection by anchor identity/entailment.
- Stage 2 declared-semantics signal: categorical, direction-aware
  (identical / entailed-broader / entailed-narrower / declared-but-unrelated /
  missing), read from the index — hash lookups, no reasoning per pair.
- Stage 4: the anchor pathway to `EXACT_MATCH` (identical anchors + compatible
  units); anchor subsumption as broad/narrow evidence.
- Unit veto extension: shared anchor + incommensurable dims → priority audit log.

**Acceptance**
- Anchored fixture pairs map with `semapv:LogicalReasoning`-family
  justification, distinct from lexical justifications.
- Reasoner invoked exactly once per ontology version (assert via call counter).

## Milestone 3 — Embeddings & semantic signals

**Scope**
- `EmbeddingBackend` implementation (model TBD; keep swappable), embedding
  index for the blocking channel, profile embeddings built from
  anchor-enriched text from day one.
- Stage 2 semantic similarity features; definition-vs-definition and
  name-vs-definition asymmetric features.

**Acceptance**
- Recall of blocking on curated set ≥ target (set from M1 curation data);
  embedding channel adds candidates the lexical channel missed (measured).

## Milestone 4 — Structure, learning, calibration

Requires curated labels from the M1/M2 loop.

**Scope**
- Stage 2 structural signal: personalized PageRank on the product graph,
  restart α, seeded with lexical+semantic pair scores (invariant 8).
- Stage 3: learned combiner + isotonic calibration, conditional on evidence
  regime (anchored vs. statistical-only), missingness as first-class.
- Stage 5: structural coherence checks + reasoner repair loop (gen-owl export,
  locality-based anchor modules, EXACT→equivalence, BROAD/NARROW→subsumption,
  never CLOSE/RELATED (invariant 6), classify, explain minimal conflict set,
  demote weakest, iterate).
- Evaluation harness: precision/recall per justification type on held-out
  curated slice.

**Acceptance**
- Calibration curve reported per evidence regime; Stage 5 demotions logged with
  the reasoner explanation attached.

## Milestone 5 — Optional, each gated on measured improvement

- Landmark diffusion coordinates over shared anchors (cross-schema structural
  feature; sparse, same adoption gradient as anchors).
- Diffusion over the mapping graph: transitive confidence for hub composition
  and review-queue ranking only (invariant 9).
- LogMap as an ensemble member; per-method evaluation lines.

**Acceptance**
- Each feature ships only if it improves the held-out metric; otherwise it is
  removed, not left dormant.
