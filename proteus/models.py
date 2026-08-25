"""Core data objects for the alignment pipeline.

Frozen dataclasses only — no stage logic here (see CLAUDE.md conventions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class Predicate(str, Enum):
    """Graded mapping vocabulary (SKOS via SSSOM)."""

    EXACT_MATCH = "skos:exactMatch"
    CLOSE_MATCH = "skos:closeMatch"
    BROAD_MATCH = "skos:broadMatch"
    NARROW_MATCH = "skos:narrowMatch"
    RELATED_MATCH = "skos:relatedMatch"


class Justification(str, Enum):
    """semapv mapping justifications. Invariant 3: statistical vs. declared
    semantics provenance is never blended."""

    LEXICAL = "semapv:LexicalMatching"
    SEMANTIC_SIMILARITY = "semapv:SemanticSimilarityThresholdMatching"
    STRUCTURAL = "semapv:StructuralMatching"
    LOGICAL_REASONING = "semapv:LogicalReasoning"
    COMPOSITE = "semapv:CompositeMatching"


class ReviewStatus(str, Enum):
    PROPOSED = "PROPOSED"  # Invariant 11: the matcher only ever emits this.


class AnchorRelation(str, Enum):
    """Categorical outcome of the declared-semantics (reasoner) signal.

    MISSING is a first-class state (invariant 4), never coerced to a number.
    """

    IDENTICAL = "identical"
    ENTAILED_BROADER = "entailed_broader"    # subject's anchor ⊒ object's
    ENTAILED_NARROWER = "entailed_narrower"  # subject's anchor ⊑ object's
    DECLARED_UNRELATED = "declared_unrelated"  # both declared, provably unrelated
    MISSING = "missing"


#: Sentinel for signals that were not computed / not computable for a pair.
#: Distinct from 0.0 (invariant 4).
MISSING: float | None = None


@dataclass(frozen=True)
class DimensionVector:
    """QUDT-style dimension exponents (L, M, T, I, Θ, N, J)."""

    L: int = 0  # length
    M: int = 0  # mass
    T: int = 0  # time
    I: int = 0  # electric current
    THETA: int = 0  # thermodynamic temperature
    N: int = 0  # amount of substance
    J: int = 0  # luminous intensity

    def compatible(self, other: "DimensionVector") -> bool:
        return self == other


@dataclass(frozen=True)
class ElementRef:
    """A registry element: a class or property of a registered schema."""

    schema_id: str
    element_id: str  # CURIE or registry IRI
    kind: str  # "class" | "property"

    @property
    def qualified(self) -> str:
        return f"{self.schema_id}#{self.element_id}"


@dataclass(frozen=True)
class MatchingProfile:
    """Stage 0 output: the evidence bundle all matching operates on."""

    ref: ElementRef
    name: str
    aliases: tuple[str, ...] = ()
    definition: str = ""
    parent_name: str = ""
    sibling_names: tuple[str, ...] = ()
    value_type: str = ""
    unit: str = ""  # UCUM-ish string as registered
    dimension: DimensionVector | None = None  # canonicalized; None = no unit info
    permissible_values: tuple[str, ...] = ()
    # Ontology anchors as declared (CURIEs). Resolution/enrichment is M2.
    exact_anchors: tuple[str, ...] = ()
    close_anchors: tuple[str, ...] = ()
    broad_anchors: tuple[str, ...] = ()
    # M2: enriched text from resolved anchor terms. Kept separate from `name`
    # and `definition` by design — provenance separation (invariant 3).
    anchor_text: str = ""


@dataclass(frozen=True)
class CandidatePair:
    """Stage 1 output. `channels` records which retrieval channel(s) admitted
    the pair — provenance that survives to the SSSOM record."""

    subject: MatchingProfile
    object: MatchingProfile
    channels: tuple[str, ...]  # e.g. ("lexical",), later ("embedding","anchor")


@dataclass(frozen=True)
class VetoRecord:
    """A pair killed by the unit veto. Logged, never silently dropped
    (invariant 1) — the veto doubles as a registry data-quality audit."""

    subject: ElementRef
    object: ElementRef
    subject_unit: str
    object_unit: str
    shared_anchor: str | None = None  # non-None ⇒ highest-priority audit item

    @property
    def priority(self) -> str:
        return "HIGH" if self.shared_anchor else "NORMAL"


@dataclass(frozen=True)
class SignalVector:
    """Stage 2 output. Each float is None when MISSING (invariant 4)."""

    pair: CandidatePair
    # -- statistical family --------------------------------------------------
    name_similarity: float | None = MISSING
    token_jaccard: float | None = MISSING
    alias_overlap: float | None = MISSING
    definition_similarity: float | None = MISSING  # M3 (embeddings)
    structural_ppr: float | None = MISSING  # M4 (personalized PageRank, α knob)
    landmark_distance: float | None = MISSING  # M5 (optional)
    # -- unit evidence (hard veto already applied in Stage 1; this is the
    #    soft residual: compatible / unknown) --------------------------------
    unit_compatible: bool | None = None  # None = unit info missing on a side
    # -- declared semantics: the reasoner signal (M2) ------------------------
    anchor_relation: AnchorRelation = AnchorRelation.MISSING

    def statistical_features(self) -> Mapping[str, float | None]:
        return {
            "name_similarity": self.name_similarity,
            "token_jaccard": self.token_jaccard,
            "alias_overlap": self.alias_overlap,
            "definition_similarity": self.definition_similarity,
            "structural_ppr": self.structural_ppr,
            "landmark_distance": self.landmark_distance,
        }


@dataclass(frozen=True)
class ScoredPair:
    """Stage 3 output: one confidence per pair, plus regime bookkeeping."""

    signals: SignalVector
    confidence: float
    calibrated: bool  # False until M4's isotonic calibration lands
    evidence_regime: str  # "anchored" | "statistical" — conditional calibration key


@dataclass(frozen=True)
class ProposedMapping:
    """Stage 4/5 output; Stage 6 serializes these as SSSOM rows."""

    subject: ElementRef
    object: ElementRef
    predicate: Predicate
    confidence: float
    justification: Justification
    review_status: ReviewStatus = ReviewStatus.PROPOSED
    comment: str = ""


@dataclass(frozen=True)
class MappingSet:
    """Stage 6 unit of output; maps to the registry MappingSet object."""

    mapping_set_id: str
    subject_schema: str
    object_schema: str
    mappings: tuple[ProposedMapping, ...]
    vetoes: tuple[VetoRecord, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
