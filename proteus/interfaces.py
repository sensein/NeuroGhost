"""Pluggable backend interfaces.

Stages never import concrete backends (CLAUDE.md conventions); the orchestrator
injects implementations of these Protocols. This is what keeps ELK → HermiT a
drop-in swap (invariant 7) and the registry mockable.
"""
from __future__ import annotations

from typing import Iterable, Protocol, Sequence, runtime_checkable

from .models import AnchorRelation, MatchingProfile


@runtime_checkable
class RegistryAdapter(Protocol):
    """Access to the (already-ingested) schema registry / graph.

    The real implementation talks to the PROTEUS registry store; the fixture
    implementation (adapters/mock_registry.py) reads YAML files.
    """

    def schema_ids(self) -> Sequence[str]: ...

    def elements(self, schema_id: str) -> Iterable[MatchingProfile]:
        """Yield matching profiles for every element of a schema.

        Stage 0 owns profile *enrichment*; the adapter owns faithful
        extraction of what the registry holds.
        """
        ...


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Text embedding provider for the embedding blocking channel and the
    semantic similarity signals (Milestone 3)."""

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@runtime_checkable
class ReasonerBackend(Protocol):
    """OWL reasoner access, amortized (invariant 5): implementations classify
    each referenced ontology ONCE per version and materialize an anchor index;
    `anchor_relation` is then a lookup, never a reasoning call.

    Default implementation target: ELK. HermiT-class reasoners must fit behind
    this same interface (invariant 7).
    """

    def materialize(self, ontology_id: str, version: str) -> None:
        """Classify and cache the ontology's entailed hierarchy."""
        ...

    def anchor_relation(
        self, subject_anchors: Sequence[str], object_anchors: Sequence[str]
    ) -> AnchorRelation:
        """Categorical declared-semantics outcome for a pair (hash lookups)."""
        ...

    def repair_conflicts(self, mapping_axioms: object) -> object:
        """Stage 5 repair loop entry point (Milestone 4). Translation rules:
        EXACT→equivalence, BROAD/NARROW→subsumption, CLOSE/RELATED never
        translated (invariant 6)."""
        ...


@runtime_checkable
class LexicalIndex(Protocol):
    """High-recall lexical retrieval for the blocking stage."""

    def build(self, profiles: Sequence[MatchingProfile]) -> None: ...

    def query(self, profile: MatchingProfile, k: int) -> Sequence[MatchingProfile]: ...
