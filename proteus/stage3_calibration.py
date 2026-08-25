"""Stage 3 — Signal combination and calibration.

M1: fixed-weight average over PRESENT statistical signals, renormalized over
the present mask (missing ≠ 0, invariant 4), plus a small bonus/penalty from
unit residual. Output flagged `calibrated=False`.

M4 replaces this with a learned combiner + isotonic calibration, conditional
on evidence regime ("anchored" vs "statistical") — anchor evidence has a
different failure mode (annotation error, not graded noise), so it must not
share a calibration curve with statistics.
"""
from __future__ import annotations

from typing import Sequence

from .models import AnchorRelation, ScoredPair, SignalVector

_WEIGHTS = {
    "name_similarity": 0.45,
    "token_jaccard": 0.35,
    "alias_overlap": 0.20,
    "definition_similarity": 0.0,  # M3
    "structural_ppr": 0.0,  # M4
    "landmark_distance": 0.0,  # M5
}


def combine(sig: SignalVector) -> ScoredPair:
    feats = sig.statistical_features()
    present = {k: v for k, v in feats.items() if v is not None and _WEIGHTS[k] > 0}
    if present:
        wsum = sum(_WEIGHTS[k] for k in present)
        score = sum(_WEIGHTS[k] * v for k, v in present.items()) / wsum
    else:
        score = 0.0
    if sig.unit_compatible is True:
        score = min(1.0, score + 0.05)
    regime = (
        "anchored"
        if sig.anchor_relation is not AnchorRelation.MISSING
        else "statistical"
    )
    return ScoredPair(
        signals=sig, confidence=round(score, 4), calibrated=False, evidence_regime=regime
    )


def combine_all(signals: Sequence[SignalVector]) -> list[ScoredPair]:
    return [combine(s) for s in signals]


def isotonic_calibrate(scored: Sequence[ScoredPair], labels) -> list[ScoredPair]:
    """Milestone 4: isotonic calibration per evidence regime, trained on the
    curated-mapping labels fed back by the review loop."""
    raise NotImplementedError(
        "Milestone 4 (docs/IMPLEMENTATION_PLAN.md); spec: Stage 3."
    )
