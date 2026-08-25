# CLAUDE.md — proteus

Alignment computation for the PROTEUS schema registry. This package proposes
semantic mappings (SSSOM) between registered schemas. The registry, ingestion,
and graph store already exist upstream; this repo consumes registry entities
through the `RegistryAdapter` interface and writes `PROPOSED` MappingSets back.

## Source of truth

`docs/alignment_pipeline_design_v2.md` is the specification. If code and spec
disagree, the spec wins. Do not "simplify" the architecture without updating the
spec first. `docs/IMPLEMENTATION_PLAN.md` defines what is built now vs. stubbed.

## Commands

```bash
pip install -e ".[dev]"        # install (pure Python, stdlib + pyyaml)
pytest                          # run tests (must pass before any commit)
python -m proteus.pipeline tests/fixtures/schema_a.yaml tests/fixtures/schema_b.yaml out.sssom.tsv
```

## Architecture (one module per stage)

```
stage0_profiles.py    MatchingProfile assembly (+ anchor enrichment, anchor index)
stage1_blocking.py    high-recall candidate generation, 3 channels + unit veto
stage2_signals.py     per-pair signal vector (7 signals)
stage3_calibration.py signal combination -> calibrated confidence
stage4_predicate.py   graded predicate assignment (exact/close/broad/narrow/related)
stage5_repair.py      global coherence repair over the candidate set
stage6_write.py       SSSOM MappingSet output, review_status=PROPOSED
pipeline.py           orchestrator; the only module that imports all stages
interfaces.py         Protocols: RegistryAdapter, EmbeddingBackend, ReasonerBackend
models.py             frozen dataclasses; no stage-specific logic here
units.py              QUDT dimension vectors + the unit veto
```

Pluggable backends live behind `interfaces.py` Protocols. Never import a
concrete backend (ELK wrapper, embedding model, registry client) inside a stage
module; stages receive backends via the orchestrator.

## Invariants — never violate these while coding

These decisions are settled design, not implementation details. An agent that
"cleans them up" is introducing bugs.

1. **The unit veto is a hard filter, never a score.** Incommensurable QUDT
   dimension vectors kill a candidate pair outright. Vetoed pairs are *logged*,
   not silently dropped (the veto doubles as a registry data-quality audit).
   A shared ontology anchor + incommensurable dimensions is logged at the
   highest priority: the two most trustworthy evidence streams disagree.
2. **Blocking is tuned for recall, everything after for precision.** A pair
   blocking discards is gone forever. Never add a precision-motivated filter
   to Stage 1 other than the unit veto.
3. **Statistical evidence and declared semantics stay separate to the end.**
   The SSSOM `mapping_justification` (semapv) must reflect which evidence
   family produced the mapping. Never blend anchor-derived features into a
   statistical score in a way that loses this provenance.
4. **Missing anchor features are missing, not zero.** Absence of an ontology
   annotation is not negative evidence. Stage 3 must handle missingness as a
   first-class state (feature masks), never impute 0.
5. **The reasoner never runs per candidate pair.** Amortization rule: once per
   ontology version (Stage 0, materialize the anchor index), once per matcher
   run (Stage 5, repair loop). Per-pair anchor checks are hash lookups against
   the materialized index.
6. **`CLOSE_MATCH` and `RELATED_MATCH` are never translated to OWL axioms**
   in Stage 5 repair. SKOS deliberately gives them no OWL semantics; forcing
   equivalence/subsumption on them manufactures false incoherence. Only
   EXACT_MATCH -> equivalence and BROAD/NARROW_MATCH -> subsumption translate.
7. **Reasoner backends are drop-in swappable.** ELK is the default; HermiT-class
   is an escalation behind the same `ReasonerBackend` Protocol. No stage may
   depend on reasoner-specific behavior.
8. **Structural propagation is personalized PageRank on the product graph**
   with restart probability α — not an ad hoc "run N rounds" loop. If you
   implement Stage 2's structural signal, α is the knob; there is no round-count
   parameter anywhere.
9. **Diffusion over the mapping graph ranks review queues only.** It never
   mints or modifies mapping confidences.
10. **The only non-LLM machine pathway to `EXACT_MATCH`** is identical anchors
    + compatible units (Stage 4). Statistical evidence alone caps at
    `CLOSE_MATCH`.
11. **Everything the matcher emits is `review_status=PROPOSED`.** The pipeline
    never promotes its own output; only the human curation loop does.

## Conventions

- Python ≥3.11, stdlib + pyyaml only in core; optional extras gated behind
  `interfaces.py` Protocols and lazy imports in `adapters/`.
- `models.py` dataclasses are `frozen=True`. Transform by constructing new
  objects, never mutate.
- Stubs raise `NotImplementedError` with a pointer to the spec section and the
  milestone in `docs/IMPLEMENTATION_PLAN.md`. Do not implement ahead of the
  current milestone without being asked.
- Every new signal or stage behavior needs a fixture-based test in `tests/`.
  The two toy schemas in `tests/fixtures/` are the shared test bed; extend
  them rather than inventing new ad hoc fixtures.
- SSSOM column names follow the SSSOM spec exactly (`subject_id`,
  `predicate_id`, `object_id`, `mapping_justification`, `confidence`, ...).
