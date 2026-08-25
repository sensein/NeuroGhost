# The Alignment Computation: Pipeline Design (v2)

> **Placeholder.** Replace this file with the canonical
> `alignment_pipeline_design_v2.md` produced in the design sessions — it is the
> source of truth for this repo (see CLAUDE.md). Summary of shape, for
> orientation until then:
>
> Six stages + composition. Stage 0 matching profiles (anchor enrichment,
> reasoner-materialized anchor index, once per ontology version). Stage 1
> high-recall blocking via embedding / lexical / anchor channels + QUDT unit
> veto. Stage 2 seven per-pair signals incl. declared semantics (reasoner
> signal) and personalized-PageRank structural diffusion (restart α). Stage 3
> calibrated combination, missingness first-class, conditional per evidence
> regime. Stage 4 graded predicate; identical anchors + compatible units is the
> one non-LLM path to EXACT_MATCH. Stage 5 coherence repair incl. reasoner
> loop (ELK default, HermiT drop-in; CLOSE/RELATED never translated to OWL).
> Stage 6 writes PROPOSED SSSOM MappingSets. Composition derives
> schema-to-schema mappings through the hub; mapping-graph diffusion ranks
> review queues only.
