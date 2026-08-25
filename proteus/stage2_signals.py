"""Stage 2 — Per-pair signal vector.

Seven signals in the full design. M1 computes the lexical family and the unit
residual; embeddings (M3), structural PPR (M4), landmark coordinates (M5), and
the declared-semantics/reasoner signal (M2) emit MISSING — which is a state,
not a zero (invariant 4).
"""
from __future__ import annotations

from typing import Sequence

from ._lexical import jaccard, string_similarity, tokens
from .interfaces import ReasonerBackend
from .models import AnchorRelation, CandidatePair, SignalVector, MISSING
from .units import unit_compatibility


def _alias_overlap(pair: CandidatePair) -> float | None:
    s_names = {pair.subject.name, *pair.subject.aliases}
    o_names = {pair.object.name, *pair.object.aliases}
    if not pair.subject.aliases and not pair.object.aliases:
        return MISSING  # no alias evidence exists on either side
    best = max(
        string_similarity(a, b) for a in s_names for b in o_names
    )
    return best


def compute_signals(
    pair: CandidatePair, reasoner: ReasonerBackend | None = None
) -> SignalVector:
    anchor_rel = AnchorRelation.MISSING
    if reasoner is not None and (
        pair.subject.exact_anchors or pair.subject.broad_anchors
    ) and (pair.object.exact_anchors or pair.object.broad_anchors):
        # M2: a hash lookup against the materialized index — never a
        # reasoning call per pair (invariant 5).
        anchor_rel = reasoner.anchor_relation(
            [*pair.subject.exact_anchors, *pair.subject.broad_anchors],
            [*pair.object.exact_anchors, *pair.object.broad_anchors],
        )
    return SignalVector(
        pair=pair,
        name_similarity=string_similarity(pair.subject.name, pair.object.name),
        token_jaccard=jaccard(tokens(pair.subject.name), tokens(pair.object.name)),
        alias_overlap=_alias_overlap(pair),
        definition_similarity=MISSING,  # M3
        structural_ppr=MISSING,  # M4: personalized PageRank on product graph, knob=α
        landmark_distance=MISSING,  # M5, gated on measured improvement
        unit_compatible=unit_compatibility(pair.subject, pair.object),
        anchor_relation=anchor_rel,
    )


def compute_all(
    pairs: Sequence[CandidatePair], reasoner: ReasonerBackend | None = None
) -> list[SignalVector]:
    return [compute_signals(p, reasoner) for p in pairs]
