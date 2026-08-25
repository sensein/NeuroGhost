"""Stage 1 — Candidate generation (blocking).

Tuned for recall (invariant 2): three parallel high-recall channels, then the
unit veto — the only precision filter permitted here (invariant 1).

M1 implements the lexical channel; embedding (M3) and anchor (M2) channels are
stubbed to empty so the merge logic and channel provenance are real now.
"""
from __future__ import annotations

from typing import Sequence

from ._lexical import jaccard, string_similarity, tokens
from .interfaces import EmbeddingBackend, ReasonerBackend
from .models import CandidatePair, MatchingProfile, VetoRecord
from .units import veto

DEFAULT_K = 25
_LEXICAL_FLOOR = 0.15  # recall guard: admit anything faintly plausible


def lexical_channel(
    subjects: Sequence[MatchingProfile],
    objects: Sequence[MatchingProfile],
    k: int = DEFAULT_K,
) -> dict[tuple[str, str], set[str]]:
    """Naive O(n·m) scoring is fine at fixture scale; swap in an inverted
    index behind interfaces.LexicalIndex when schemas grow."""
    admitted: dict[tuple[str, str], set[str]] = {}
    for s in subjects:
        scored = []
        for o in objects:
            if s.ref.kind != o.ref.kind:
                continue
            score = max(
                string_similarity(s.name, o.name),
                jaccard(tokens(s.name), tokens(o.name)),
                max(
                    (string_similarity(a, o.name) for a in s.aliases),
                    default=0.0,
                ),
                max(
                    (string_similarity(s.name, a) for a in o.aliases),
                    default=0.0,
                ),
            )
            if score >= _LEXICAL_FLOOR:
                scored.append((score, o))
        scored.sort(key=lambda t: -t[0])
        for _, o in scored[:k]:
            admitted.setdefault((s.ref.qualified, o.ref.qualified), set()).add("lexical")
    return admitted


def embedding_channel(*args, **kwargs) -> dict[tuple[str, str], set[str]]:
    """Milestone 3."""
    return {}


def anchor_channel(*args, **kwargs) -> dict[tuple[str, str], set[str]]:
    """Milestone 2: inject candidates by anchor identity/entailment — pairs
    the statistical channels cannot reach."""
    return {}


def generate_candidates(
    subjects: Sequence[MatchingProfile],
    objects: Sequence[MatchingProfile],
    embedder: EmbeddingBackend | None = None,
    reasoner: ReasonerBackend | None = None,
    k: int = DEFAULT_K,
) -> tuple[list[CandidatePair], list[VetoRecord]]:
    by_id_s = {p.ref.qualified: p for p in subjects}
    by_id_o = {p.ref.qualified: p for p in objects}

    merged = lexical_channel(subjects, objects, k)
    for extra in (
        embedding_channel(subjects, objects, embedder, k),
        anchor_channel(subjects, objects, reasoner),
    ):
        for key, chans in extra.items():
            merged.setdefault(key, set()).update(chans)

    pairs: list[CandidatePair] = []
    vetoes: list[VetoRecord] = []
    for (sid, oid), chans in sorted(merged.items()):
        s, o = by_id_s[sid], by_id_o[oid]
        v = veto(s, o)
        if v is not None:
            vetoes.append(v)  # logged, never silently dropped (invariant 1)
            continue
        pairs.append(CandidatePair(subject=s, object=o, channels=tuple(sorted(chans))))
    return pairs, vetoes
