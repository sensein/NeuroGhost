"""Placeholder ReasonerBackend for tests: anchor identity only, no entailment.

The real M2 backend wraps ELK (robot reason / owlapi), materializes the
classified hierarchy once per ontology version, and answers entailment from
the cached index. HermiT-class reasoners slot behind the same Protocol
(invariant 7).
"""
from __future__ import annotations

from typing import Sequence

from ..models import AnchorRelation


class IdentityOnlyReasoner:
    def materialize(self, ontology_id: str, version: str) -> None:
        pass

    def anchor_relation(
        self, subject_anchors: Sequence[str], object_anchors: Sequence[str]
    ) -> AnchorRelation:
        s, o = set(subject_anchors), set(object_anchors)
        if not s or not o:
            return AnchorRelation.MISSING
        if s & o:
            return AnchorRelation.IDENTICAL
        # Without entailment (M2) we cannot distinguish unrelated from
        # related-but-not-asserted; stay conservative.
        return AnchorRelation.MISSING

    def repair_conflicts(self, mapping_axioms: object) -> object:
        raise NotImplementedError("Milestone 4; spec: Stage 5.")
