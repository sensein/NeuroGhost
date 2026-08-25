"""Stage 4 — Graded predicate assignment.

Invariant 10: statistical evidence alone caps at CLOSE_MATCH. The single
non-LLM machine pathway to EXACT_MATCH — identical anchors + compatible
units — arrives with M2 and is already wired below. Anchor subsumption is the
cleanest broad/narrow evidence.
"""
from __future__ import annotations

from typing import Sequence

from .models import (
    AnchorRelation,
    Justification,
    Predicate,
    ProposedMapping,
    ScoredPair,
)

CONFIDENCE_FLOOR = 0.45  # below this, the pair is dropped (not emitted at all)


def assign(scored: ScoredPair) -> ProposedMapping | None:
    sig = scored.signals
    s, o = sig.pair.subject.ref, sig.pair.object.ref
    channels = ",".join(sig.pair.channels)

    # --- declared-semantics pathways (M2; reasoner signal) ------------------
    if sig.anchor_relation is AnchorRelation.IDENTICAL and sig.unit_compatible:
        return ProposedMapping(
            subject=s, object=o, predicate=Predicate.EXACT_MATCH,
            confidence=max(scored.confidence, 0.95),
            justification=Justification.LOGICAL_REASONING,
            comment=f"identical anchors + compatible units; channels={channels}",
        )
    if sig.anchor_relation is AnchorRelation.ENTAILED_NARROWER:
        return ProposedMapping(
            subject=s, object=o, predicate=Predicate.BROAD_MATCH,
            confidence=max(scored.confidence, 0.85),
            justification=Justification.LOGICAL_REASONING,
            comment=f"anchor entailment (subject narrower); channels={channels}",
        )
    if sig.anchor_relation is AnchorRelation.ENTAILED_BROADER:
        return ProposedMapping(
            subject=s, object=o, predicate=Predicate.NARROW_MATCH,
            confidence=max(scored.confidence, 0.85),
            justification=Justification.LOGICAL_REASONING,
            comment=f"anchor entailment (subject broader); channels={channels}",
        )

    # --- statistical pathway (caps at CLOSE_MATCH, invariant 10) ------------
    if scored.confidence < CONFIDENCE_FLOOR:
        return None
    predicate = Predicate.CLOSE_MATCH if scored.confidence >= 0.65 else Predicate.RELATED_MATCH
    return ProposedMapping(
        subject=s, object=o, predicate=predicate,
        confidence=scored.confidence,
        justification=Justification.LEXICAL,  # M1: only lexical stats present
        comment=f"uncalibrated (M1); regime={scored.evidence_regime}; channels={channels}",
    )


def assign_all(scored: Sequence[ScoredPair]) -> list[ProposedMapping]:
    return [m for m in (assign(sp) for sp in scored) if m is not None]
