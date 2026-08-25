"""Core data objects for the alignment pipeline — v4 meta-model.

Frozen dataclasses only — no stage logic here (see CLAUDE.md conventions).

Identity contract (v4): hash_id is derived from HashSubset slots only.
Schema version is NOT in the hash; version membership lives on
SourceSchemaVersion. Entities never merge across schemas by content hash —
every correspondence is an explicit SSSOM Mapping with justification,
confidence, and review_status.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


# ── Enumerations ───────────────────────────────────────────────────────────────

class Predicate(str, Enum):
    """Graded mapping vocabulary (SKOS via SSSOM) + OWL equivalence (v4)."""

    EXACT_MATCH = "skos:exactMatch"
    CLOSE_MATCH = "skos:closeMatch"
    BROAD_MATCH = "skos:broadMatch"
    NARROW_MATCH = "skos:narrowMatch"
    RELATED_MATCH = "skos:relatedMatch"
    EQUIVALENT_CLASS = "owl:equivalentClass"  # v4: declared-semantics only (invariant 6)


class Justification(str, Enum):
    """semapv mapping justifications. Invariant 3: statistical vs. declared
    semantics provenance is never blended."""

    LEXICAL = "semapv:LexicalMatching"
    SEMANTIC_SIMILARITY = "semapv:SemanticSimilarityThresholdMatching"
    STRUCTURAL = "semapv:StructuralMatching"
    LOGICAL_REASONING = "semapv:LogicalReasoning"
    COMPOSITE = "semapv:CompositeMatching"
    UNSPECIFIED = "semapv:UnspecifiedMatching"  # v4


class ReviewStatus(str, Enum):
    """v4: four-state review lifecycle. Matcher only ever emits PROPOSED (invariant 11)."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AnchorRelation(str, Enum):
    """Categorical outcome of the declared-semantics (reasoner) signal.

    MISSING is a first-class state (invariant 4), never coerced to a number.
    """

    IDENTICAL = "identical"
    ENTAILED_BROADER = "entailed_broader"    # subject's anchor ⊒ object's
    ENTAILED_NARROWER = "entailed_narrower"  # subject's anchor ⊑ object's
    DECLARED_UNRELATED = "declared_unrelated"
    MISSING = "missing"


#: Sentinel for signals not computed / not computable. Distinct from 0.0 (invariant 4).
MISSING: float | None = None


# ── Unit modeling (v4: QUDT-aligned) ──────────────────────────────────────────

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
class UnitOfMeasure:
    """v4: structured unit — QUDT IRI + UCUM code + quantity kind.

    has_quantity_kind enables a cheap first-tier veto (incommensurable
    quantity kinds reject before any conversion lookup). dimension is the
    canonicalized DimensionVector; None means no unit info available.
    """

    qudt_unit: str = ""          # e.g. "unit:MilliSEC"
    ucum_code: str = ""          # e.g. "ms"  (used in veto and SSSOM output)
    has_quantity_kind: str = ""  # e.g. "quantitykind:Time"
    symbol: str = ""
    unit_label: str = ""
    dimension: DimensionVector | None = None  # canonicalized from ucum_code


# ── Provenance (v4: PROV-O) ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProvenanceInfo:
    """W3C PROV-O slots attached to every registry entity (v4)."""

    was_attributed_to: str = ""        # agent IRI
    generated_at_time: str = ""        # ISO-8601
    was_generated_by: str = ""         # "ingestion" | "manual" | "alignment"
    had_primary_source: str = ""       # SourceSchemaVersion id that first produced this entity
    derived_from: tuple[str, ...] = () # predecessor entity hash_ids


# ── Identity hashing (v4 contract) ────────────────────────────────────────────

def _compute_hash(hash_subset: dict) -> str:
    """SHA-256 over canonical JSON of HashSubset fields.

    Multivalued slots are sorted before hashing (v4: canonical ordering).
    Version is never in the hash — version membership lives on SourceSchemaVersion.
    """
    canonical = json.dumps(hash_subset, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Registry-level objects (v4) ────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceSchema:
    """Mutable administrative record for a registered schema."""

    schema_id: str          # stable IRI / CURIE
    name: str
    description: str = ""
    is_hub: bool = False    # ifabsent: false — prevents null/false hash collision


@dataclass(frozen=True)
class SourceSchemaVersion:
    """Immutable version anchor.

    entities is the manifest of entity hash_ids at this version.
    Cross-version diff is a set-difference of two manifests.
    """

    version_id: str                    # e.g. "schema:x@v1.2.3"
    schema_id: str
    version_label: str = ""
    artifact_hash: str = ""            # SHA-256 of the source artifact
    prior_version: str = ""            # version_id of predecessor
    entities: tuple[str, ...] = ()     # hash_id manifest


@dataclass(frozen=True)
class SlotAssignment:
    """v4: Association linking a property to a class with cardinality constraints."""

    property_id: str               # hash_id of the RegistryProperty
    required: bool = False         # ifabsent: false
    multivalued: bool = False
    minimum_cardinality: int | None = None
    maximum_cardinality: int | None = None


@dataclass(frozen=True)
class Relation:
    """v4: A declared relationship between two classes (is_a, mixin, related_to)."""

    predicate: str   # "is_a" | "mixin" | "related_to"
    object_id: str   # hash_id of the target RegistryClass


@dataclass(frozen=True)
class RegistryEntity:
    """v4: Base registry entity. hash_id is content-addressed from HashSubset slots.

    Entities never merge across schemas by hash — identical content in two
    schemas produces two distinct entities. Every correspondence is an explicit
    SSSOM Mapping (no implicit exactMatch).
    """

    # HashSubset fields — all contribute to hash_id
    name: str
    source_native_id: str           # verbatim identifier from the source
    definition: str
    declared_uri: str               # source's claimed semantic IRI
    defined_in_schema: str          # schema_id (in hash; version excluded)
    aliases: tuple[str, ...] = ()   # sorted before hashing (v4 canonical ordering)
    # Non-hash fields
    provenance: ProvenanceInfo = field(default_factory=ProvenanceInfo)

    @property
    def hash_id(self) -> str:
        return _compute_hash({
            "name": self.name,
            "source_native_id": self.source_native_id,
            "definition": self.definition,
            "declared_uri": self.declared_uri,
            "defined_in_schema": self.defined_in_schema,
            "aliases": sorted(self.aliases),
        })


@dataclass(frozen=True)
class RegistryClass(RegistryEntity):
    """v4: Object type entity."""

    abstract: bool = False                        # ifabsent: false (hash stability)
    parent_class: str = ""                        # hash_id of parent (in hash)
    mixins: tuple[str, ...] = ()                  # hash_ids, sorted before hashing
    slot_assignments: tuple[SlotAssignment, ...] = ()
    relations: tuple[Relation, ...] = ()

    @property
    def hash_id(self) -> str:
        return _compute_hash({
            "name": self.name,
            "source_native_id": self.source_native_id,
            "definition": self.definition,
            "declared_uri": self.declared_uri,
            "defined_in_schema": self.defined_in_schema,
            "aliases": sorted(self.aliases),
            "abstract": self.abstract,
            "parent_class": self.parent_class,
            "mixins": sorted(self.mixins),
        })


@dataclass(frozen=True)
class RegistryProperty(RegistryEntity):
    """v4: Data element entity. Unit modeling follows QUDT (has_quantity_kind veto)."""

    value_type: str = ""                           # in hash
    unit: UnitOfMeasure = field(default_factory=UnitOfMeasure)  # in hash

    @property
    def hash_id(self) -> str:
        return _compute_hash({
            "name": self.name,
            "source_native_id": self.source_native_id,
            "definition": self.definition,
            "declared_uri": self.declared_uri,
            "defined_in_schema": self.defined_in_schema,
            "aliases": sorted(self.aliases),
            "value_type": self.value_type,
            "unit_qudt": self.unit.qudt_unit,
            "unit_ucum": self.unit.ucum_code,
            "unit_quantity_kind": self.unit.has_quantity_kind,
        })


@dataclass(frozen=True)
class ValueSet(RegistryEntity):
    """v4: Enumerated value set entity."""

    permissible_values: tuple[str, ...] = ()  # sorted before hashing

    @property
    def hash_id(self) -> str:
        return _compute_hash({
            "name": self.name,
            "source_native_id": self.source_native_id,
            "definition": self.definition,
            "declared_uri": self.declared_uri,
            "defined_in_schema": self.defined_in_schema,
            "aliases": sorted(self.aliases),
            "permissible_values": sorted(self.permissible_values),
        })


# ── Pipeline-internal objects ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ElementRef:
    """Lightweight reference to a registry element used inside pipeline stages."""

    schema_id: str
    element_id: str   # source_native_id / CURIE
    kind: str         # "class" | "property" | "value_set"

    @property
    def qualified(self) -> str:
        return f"{self.schema_id}#{self.element_id}"


@dataclass(frozen=True)
class MatchingProfile:
    """Stage 0 output: the evidence bundle all matching stages operate on.

    unit is a structured UnitOfMeasure (v4); dimension lives on unit.dimension.
    Anchor text kept separate from name/definition — provenance separation (invariant 3).
    """

    ref: ElementRef
    name: str
    aliases: tuple[str, ...] = ()
    definition: str = ""
    parent_name: str = ""
    sibling_names: tuple[str, ...] = ()
    value_type: str = ""
    unit: UnitOfMeasure = field(default_factory=UnitOfMeasure)  # v4: replaces unit:str + dimension
    permissible_values: tuple[str, ...] = ()
    # Ontology anchors as declared (CURIEs). Resolution/enrichment is M2.
    exact_anchors: tuple[str, ...] = ()
    close_anchors: tuple[str, ...] = ()
    broad_anchors: tuple[str, ...] = ()
    # M2: enriched text from resolved anchor terms — never mixed into name/definition (invariant 3).
    anchor_text: str = ""


@dataclass(frozen=True)
class CandidatePair:
    """Stage 1 output. channels records which retrieval channel(s) admitted the pair."""

    subject: MatchingProfile
    object: MatchingProfile
    channels: tuple[str, ...]  # e.g. ("lexical",), later ("embedding", "anchor")


@dataclass(frozen=True)
class VetoRecord:
    """A pair killed by the unit veto. Logged, never silently dropped (invariant 1).

    The veto doubles as a registry data-quality audit.
    shared_anchor non-None means the two most trustworthy evidence streams disagree.
    """

    subject: ElementRef
    object: ElementRef
    subject_unit: str   # ucum_code of the subject's unit
    object_unit: str    # ucum_code of the object's unit
    shared_anchor: str | None = None

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
    definition_similarity: float | None = MISSING   # M3 (embeddings)
    structural_ppr: float | None = MISSING          # M4 (personalized PageRank, α knob)
    landmark_distance: float | None = MISSING       # M5 (optional)
    # -- unit evidence: soft residual after hard veto in Stage 1 --------------
    unit_compatible: bool | None = None             # None = unit info missing on a side
    # -- declared semantics: the reasoner signal (M2) -------------------------
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
    """Stage 3 output: one calibrated confidence per pair."""

    signals: SignalVector
    confidence: float
    calibrated: bool         # False until M4's isotonic calibration lands
    evidence_regime: str     # "anchored" | "statistical" — conditional calibration key


@dataclass(frozen=True)
class ProposedMapping:
    """Stage 4/5 output; Stage 6 serializes as SSSOM rows.

    v4: author_id, reviewer_id, mapping_date added for PROV attribution.
    Invariant 11: review_status is always PROPOSED from the matcher.
    """

    subject: ElementRef
    object: ElementRef
    predicate: Predicate
    confidence: float
    justification: Justification
    review_status: ReviewStatus = ReviewStatus.PROPOSED
    author_id: str = ""      # v4: agent IRI of the matcher run
    reviewer_id: str = ""    # v4: set by the curation loop, not the matcher
    mapping_date: str = ""   # v4: ISO-8601
    comment: str = ""


@dataclass(frozen=True)
class MappingSet:
    """Stage 6 unit of output; maps to the registry MappingSet / SSSOM TSV named graph."""

    mapping_set_id: str
    subject_schema: str
    object_schema: str
    mappings: tuple[ProposedMapping, ...]
    vetoes: tuple[VetoRecord, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
