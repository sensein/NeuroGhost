"""Stage 0 — Matching profiles.

M1: pass-through from the registry adapter (unit canonicalization applied).
M2 adds: anchor enrichment (resolved term label/synonyms/definition into the
separate `anchor_text` field) and the reasoner-materialized anchor index —
built once per ontology version (invariant 5).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Sequence

from .interfaces import RegistryAdapter, ReasonerBackend
from .models import MatchingProfile
from .units import dimension_of


def build_profiles(
    registry: RegistryAdapter,
    schema_id: str,
    reasoner: ReasonerBackend | None = None,
) -> Sequence[MatchingProfile]:
    profiles = []
    for p in registry.elements(schema_id):
        if p.dimension is None and p.unit:
            p = replace(p, dimension=dimension_of(p.unit))
        profiles.append(p)
    if reasoner is not None:
        _enrich_anchors(profiles, reasoner)
    return profiles


def _enrich_anchors(
    profiles: Iterable[MatchingProfile], reasoner: ReasonerBackend
) -> None:
    """Milestone 2. Resolve anchor CURIEs, fetch label/synonyms/definition
    into `anchor_text`, and ensure the anchor index is materialized once per
    referenced ontology version."""
    raise NotImplementedError(
        "Milestone 2 (docs/IMPLEMENTATION_PLAN.md); spec: Stage 0, anchor enrichment."
    )
