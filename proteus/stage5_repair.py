"""Stage 5 — Global coherence repair.

M1 ships a cheap structural sanity check (1-to-many EXACT conflicts get the
weaker member demoted) so the demote-don't-delete pattern is established.

M4 adds the reasoner repair loop per spec: gen-owl exports + locality-based
anchor modules; translate EXACT→equivalence, BROAD/NARROW→subsumption,
NEVER CLOSE/RELATED (invariant 6); classify (ELK default, HermiT drop-in
behind ReasonerBackend, invariant 7); use the explanation facility to find the
minimal conflicting mapping subset; demote its weakest member; repeat until
coherent. Runs once per matcher run (invariant 5).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Sequence

from .interfaces import ReasonerBackend
from .models import Predicate, ProposedMapping


def structural_sanity(mappings: Sequence[ProposedMapping]) -> list[ProposedMapping]:
    """If one subject holds multiple EXACT_MATCH claims, keep the strongest,
    demote the rest to CLOSE_MATCH (demote, never delete)."""
    by_subject: dict[str, list[ProposedMapping]] = defaultdict(list)
    for m in mappings:
        by_subject[f"{m.subject.schema_id}#{m.subject.element_id}"].append(m)

    out: list[ProposedMapping] = []
    for group in by_subject.values():
        exacts = sorted(
            (m for m in group if m.predicate is Predicate.EXACT_MATCH),
            key=lambda m: -m.confidence,
        )
        others = [m for m in group if m.predicate is not Predicate.EXACT_MATCH]
        out.extend(exacts[:1])
        out.extend(
            replace(m, predicate=Predicate.CLOSE_MATCH,
                    comment=m.comment + " | demoted: EXACT cardinality conflict")
            for m in exacts[1:]
        )
        out.extend(others)
    return out


def reasoner_repair(
    mappings: Sequence[ProposedMapping], reasoner: ReasonerBackend
) -> list[ProposedMapping]:
    """Milestone 4. See module docstring for the loop; every demotion must log
    the reasoner explanation that indicted it."""
    raise NotImplementedError(
        "Milestone 4 (docs/IMPLEMENTATION_PLAN.md); spec: Stage 5, reasoner repair."
    )


def repair(
    mappings: Sequence[ProposedMapping], reasoner: ReasonerBackend | None = None
) -> list[ProposedMapping]:
    out = structural_sanity(mappings)
    if reasoner is not None:
        out = reasoner_repair(out, reasoner)
    return out
