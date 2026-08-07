# ---------------------------------------------------------------------------
# GENERATED FILE — DO NOT EDIT BY HAND.
#
# Produced by ./scripts/gen_models.sh from schemas/meta_model.yaml.
# Edit the schema and regenerate; hand edits are overwritten by
# .github/workflows/gen_models.yml on the next schema change.
# ---------------------------------------------------------------------------
from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'screg',
     'default_range': 'string',
     'description': 'Meta-model for the schema registry: defines the registered '
                    'object types (RegistryClass, RegistryProperty, and related '
                    'support classes) used to describe classes and data elements '
                    'that can be registered, versioned, related to each other, and '
                    'compared for similarity. NOTE: `id` above is a placeholder '
                    'namespace — replace before publishing.',
     'id': 'https://example.org/schema-registry-utils/meta-model',
     'imports': ['linkml:types'],
     'name': 'schema_registry_meta_model',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'prov': {'prefix_prefix': 'prov',
                           'prefix_reference': 'http://www.w3.org/ns/prov#'},
                  'qudt': {'prefix_prefix': 'qudt',
                           'prefix_reference': 'http://qudt.org/schema/qudt/'},
                  'rdfs': {'prefix_prefix': 'rdfs',
                           'prefix_reference': 'http://www.w3.org/2000/01/rdf-schema#'},
                  'screg': {'prefix_prefix': 'screg',
                            'prefix_reference': 'https://example.org/schema-registry-utils/'},
                  'skos': {'prefix_prefix': 'skos',
                           'prefix_reference': 'http://www.w3.org/2004/02/skos/core#'}},
     'source_file': 'schemas/meta_model.yaml',
     'subsets': {'HashSubset': {'description': 'Slots that are part of a '
                                               "RegistryEntity subclass's content "
                                               'hash (hash_id). '
                                               'schema_registry_utils/hashing.py '
                                               'derives the identity field set '
                                               "from each field's in_subset "
                                               'metadata.',
                                'from_schema': 'https://example.org/schema-registry-utils/meta-model',
                                'name': 'HashSubset'}}} )

class SkosMappingTypeEnum(str, Enum):
    """
    The kind of SKOS mapping relation between a registry entity and an external concept.
    """
    EXACT_MATCH = "EXACT_MATCH"
    """
    The registry entity is equivalent to the external concept.
    """
    CLOSE_MATCH = "CLOSE_MATCH"
    """
    The registry entity is sufficiently similar to the external concept.
    """
    BROAD_MATCH = "BROAD_MATCH"
    """
    The external concept is broader than the registry entity.
    """
    NARROW_MATCH = "NARROW_MATCH"
    """
    The external concept is narrower than the registry entity.
    """
    RELATED_MATCH = "RELATED_MATCH"
    """
    The registry entity is related to the external concept.
    """


class ReviewStatusEnum(str, Enum):
    """
    Curation lifecycle of a Mapping.
    """
    PROPOSED = "PROPOSED"
    """
    Machine- or human-proposed; not yet reviewed.
    """
    ACCEPTED = "ACCEPTED"
    """
    Validated by a reviewer; safe for high-rigor queries.
    """
    REJECTED = "REJECTED"
    """
    Reviewed and refuted; retained as negative evidence.
    """
    SUPERSEDED = "SUPERSEDED"
    """
    Replaced by a newer mapping.
    """



class RegistryEntity(ConfiguredBaseModel):
    """
    Common base for content-addressed, provenance-tracked objects registered in the schema registry. Identity (hash_id) is derived from content, so there is no separate version slot: a change produces a new hash_id, with lineage tracked via derived_from on each ProvenanceEntry.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })
    skos_mappings: Optional[list[Mapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts, or to other registry entities (align.py's computed correspondences).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })
    aliases: Optional[list[str]] = Field(default=None, description="""Alternate names/synonyms/abbreviations for this entity (e.g. \"lfp\" for \"local field potential\"), preserved from the source schema. Used as alignment evidence (align.py's alias_overlap signal) — not part of the schema's own semantics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity'], 'slot_uri': 'skos:altLabel'} })


class RegistryClass(RegistryEntity):
    """
    A registered class (object class) representing a concept or entity type in the registry, e.g. \"Patient\".
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    properties: Optional[list[str]] = Field(default=None, description="""The set of properties that belong to this class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'], 'in_subset': ['HashSubset']} })
    is_a: Optional[str] = Field(default=None, description="""The class this class inherits from (stored as hash_id FK).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'linkml:is_a'} })
    mixins: Optional[list[str]] = Field(default=None, description="""Additional classes mixed into this class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'], 'in_subset': ['HashSubset']} })
    class_uri: Optional[str] = Field(default=None, description="""Ontology IRI for this class, preserved from the source schema on ingestion. Not part of the content hash; used for alignment and cross-source lookup.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'], 'slot_uri': 'linkml:class_uri'} })
    abstract: Optional[bool] = Field(default=False, description="""Whether this registered class is itself declared abstract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'],
         'ifabsent': 'false',
         'in_subset': ['HashSubset'],
         'slot_uri': 'linkml:abstract'} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })
    skos_mappings: Optional[list[Mapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts, or to other registry entities (align.py's computed correspondences).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })
    aliases: Optional[list[str]] = Field(default=None, description="""Alternate names/synonyms/abbreviations for this entity (e.g. \"lfp\" for \"local field potential\"), preserved from the source schema. Used as alignment evidence (align.py's alias_overlap signal) — not part of the schema's own semantics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity'], 'slot_uri': 'skos:altLabel'} })


class RegistryProperty(RegistryEntity):
    """
    A registered property (data element) representing a characteristic or attribute that can be attached to a RegistryClass, e.g. \"age\". Usage constraints (required, multivalued, min/max, pattern) are deliberately not here — they belong on Rule, since the same property can be required in one source's usage and optional in another's without being a different concept.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    range: str = Field(default=..., description="""The data type or value range for this property (e.g. a primitive type name such as \"string\" or \"integer\", or the hash_id of a ValueSet for enumerated values).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'linkml:range'} })
    unit: Optional[UnitOfMeasure] = Field(default=None, description="""Structured unit of measure for this property's values, if applicable. ucum_code is the primary field for programmatic unit-compatibility checks (align.py's unit veto); the others are supplementary.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'qudt:unit'} })
    slot_uri: Optional[str] = Field(default=None, description="""Ontology IRI for this property, preserved from the source schema on ingestion. Not part of the content hash; used for alignment and cross-source lookup.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })
    skos_mappings: Optional[list[Mapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts, or to other registry entities (align.py's computed correspondences).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })
    aliases: Optional[list[str]] = Field(default=None, description="""Alternate names/synonyms/abbreviations for this entity (e.g. \"lfp\" for \"local field potential\"), preserved from the source schema. Used as alignment evidence (align.py's alias_overlap signal) — not part of the schema's own semantics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity'], 'slot_uri': 'skos:altLabel'} })


class ProvenanceEntry(ConfiguredBaseModel):
    """
    One source's attestation of a registry entity — where it came from and how/when this record was generated (W3C PROV-O fields). An entity accumulates one ProvenanceEntry per source that attests to it; identity (hash_id) never depends on provenance, so the same entity can carry many. Stored as its own node, linked via HAS_PROVENANCE / HAS_PROVENANCE_P edges (multivalued — cannot be inlined into the parent's node table). Identified by id, not hash_id — a ProvenanceEntry is a per-attestation record, not a deduplicated, content-addressed registry entity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    id: str = Field(default=..., description="""Plain unique identifier, used by every class that isn't part of the content-addressed RegistryEntity family (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping) — LinkML's own conventional name for a non-content-derived identifier. hash_id is reserved for RegistryEntity subclasses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry',
                       'Mapping',
                       'SchemaSource',
                       'SchemaVersionSnapshot']} })
    had_primary_source: str = Field(default=..., description="""The SchemaSource this attestation came from (stored as id FK, like is_a). A real Entity->Entity link, not a denormalized label copy — PROV-O's own hadPrimarySource is a relationship between entities.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:hadPrimarySource'} })
    source_description: Optional[str] = Field(default=None, description="""This source's own description text for the entity, if it differs from the entity's merged description. No direct PROV-O term; a registry-specific extension.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself. No PROV-O term — purely our own versioning concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    generated_at_time: datetime  = Field(default=..., description="""ISO-8601 timestamp this ProvenanceEntry was generated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:generatedAtTime'} })
    was_attributed_to: str = Field(default=..., description="""Agent (user or system) that generated this ProvenanceEntry.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasAttributedTo'} })
    was_generated_by: Optional[str] = Field(default=None, description="""The activity that produced this ProvenanceEntry, e.g. \"ingestion\", \"manual\", \"alignment\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasGeneratedBy'} })
    was_derived_from: Optional[list[str]] = Field(default=None, description="""hash_ids of entities this entity was derived from, if any. Stored as a native list column in the graph database.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasDerivedFrom'} })


class MappingProvenanceEntry(ProvenanceEntry):
    """
    ProvenanceEntry, but had_primary_source isn't required — a Mapping is often cross-schema (comparing content from two sources) or produced by a pure algorithmic process with no single schema to attribute to, unlike a RegistryClass/RegistryProperty attestation which always traces back to exactly one SchemaSource. Also carries the fields that describe *how* the mapping was produced (justification, evidence, tool) — those belong here rather than on Mapping itself, alongside was_generated_by/generated_at_time.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model',
         'slot_usage': {'had_primary_source': {'name': 'had_primary_source',
                                               'required': False}}})

    mapping_justification: Optional[str] = Field(default=None, description="""How this mapping came to be, e.g. \"manual\" for a source-schema- declared mapping, or \"exact_class_uri\" for align.py's placeholder. Plain string for now rather than a controlled vocabulary (e.g. semapv) — nothing yet produces enough distinct justifications to need one.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MappingProvenanceEntry']} })
    match_string: Optional[list[str]] = Field(default=None, description="""The strings/evidence the match was made on, if any.""", json_schema_extra = { "linkml_meta": {'domain_of': ['MappingProvenanceEntry']} })
    mapping_tool: Optional[str] = Field(default=None, description="""Name of the tool/process that produced this mapping, e.g. \"align.py\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['MappingProvenanceEntry']} })
    id: str = Field(default=..., description="""Plain unique identifier, used by every class that isn't part of the content-addressed RegistryEntity family (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping) — LinkML's own conventional name for a non-content-derived identifier. hash_id is reserved for RegistryEntity subclasses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry',
                       'Mapping',
                       'SchemaSource',
                       'SchemaVersionSnapshot']} })
    had_primary_source: Optional[str] = Field(default=None, description="""The SchemaSource this attestation came from (stored as id FK, like is_a). A real Entity->Entity link, not a denormalized label copy — PROV-O's own hadPrimarySource is a relationship between entities.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:hadPrimarySource'} })
    source_description: Optional[str] = Field(default=None, description="""This source's own description text for the entity, if it differs from the entity's merged description. No direct PROV-O term; a registry-specific extension.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself. No PROV-O term — purely our own versioning concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    generated_at_time: datetime  = Field(default=..., description="""ISO-8601 timestamp this ProvenanceEntry was generated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:generatedAtTime'} })
    was_attributed_to: str = Field(default=..., description="""Agent (user or system) that generated this ProvenanceEntry.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasAttributedTo'} })
    was_generated_by: Optional[str] = Field(default=None, description="""The activity that produced this ProvenanceEntry, e.g. \"ingestion\", \"manual\", \"alignment\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasGeneratedBy'} })
    was_derived_from: Optional[list[str]] = Field(default=None, description="""hash_ids of entities this entity was derived from, if any. Stored as a native list column in the graph database.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasDerivedFrom'} })


class Mapping(ConfiguredBaseModel):
    """
    A semantic mapping from a registry entity to a target — another registry entity (by hash_id) or an external vocabulary concept (by IRI). Covers both a source-declared mapping and one align.py computes, distinguished by provenance.mapping_justification, not by class. Identified by id, not hash_id — not is_a RegistryEntity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model',
         'slot_usage': {'provenance': {'name': 'provenance',
                                       'range': 'MappingProvenanceEntry'}}})

    id: str = Field(default=..., description="""Plain unique identifier, used by every class that isn't part of the content-addressed RegistryEntity family (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping) — LinkML's own conventional name for a non-content-derived identifier. hash_id is reserved for RegistryEntity subclasses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry',
                       'Mapping',
                       'SchemaSource',
                       'SchemaVersionSnapshot']} })
    mapping_type: Optional[SkosMappingTypeEnum] = Field(default=None, description="""The kind of SKOS mapping relation this represents.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Mapping']} })
    target: Optional[str] = Field(default=None, description="""What this mapping points to — an external ontology concept (IRI), or another registry entity's hash_id for align.py's computed cross-schema correspondences.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Mapping']} })
    confidence: Optional[float] = Field(default=None, description="""Score in [0,1] assigned by whatever process produced this mapping. Not required — a manually-declared mapping may have no numeric score.""", ge=0.0, le=1.0, json_schema_extra = { "linkml_meta": {'domain_of': ['Mapping']} })
    review_status: Optional[ReviewStatusEnum] = Field(default=None, description="""Curation lifecycle state. Always PROPOSED for now — nothing in this registry curates mappings yet, so this field exists to be standards-conformant (SSSOM/Proteus), not because anything sets it to ACCEPTED/REJECTED today.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Mapping']} })
    provenance: list[MappingProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })


class Rule(ConfiguredBaseModel):
    """
    STUB — a validation or business rule applicable to one or more registry entities (e.g. min/max value, pattern, required, multivalued constraints on a RegistryProperty). Slots intentionally minimal; scope TBD.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })


class Transform(ConfiguredBaseModel):
    """
    STUB — a transformation between two RegistryClass definitions. Slots intentionally minimal; scope TBD.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })


class PermissibleValue(RegistryEntity):
    """
    A single permissible value within a ValueSet enumeration. The `name` field holds the value text (e.g. \"EXACT_MATCH\"); `meaning` optionally maps it to an external ontology IRI. Identity is content-addressed on (name, description, meaning) — identical values across sources share one node, with provenance accumulating like any other RegistryEntity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    meaning: Optional[str] = Field(default=None, description="""Ontology IRI this permissible value maps to (e.g. skos:exactMatch for the EXACT_MATCH value in SkosMappingTypeEnum).""", json_schema_extra = { "linkml_meta": {'domain_of': ['PermissibleValue'], 'in_subset': ['HashSubset']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })
    skos_mappings: Optional[list[Mapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts, or to other registry entities (align.py's computed correspondences).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })
    aliases: Optional[list[str]] = Field(default=None, description="""Alternate names/synonyms/abbreviations for this entity (e.g. \"lfp\" for \"local field potential\"), preserved from the source schema. Used as alignment evidence (align.py's alias_overlap signal) — not part of the schema's own semantics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity'], 'slot_uri': 'skos:altLabel'} })


class ValueSet(RegistryEntity):
    """
    A controlled set of permissible values, usable as a RegistryProperty range. LinkML enums ingest as ValueSet nodes; each permissible value becomes a separate PermissibleValue node linked via HAS_PERMISSIBLE_VALUE edges.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    permissible_values: Optional[list[str]] = Field(default=None, description="""The set of permissible values for this ValueSet. Stored as hash_id references; HAS_PERMISSIBLE_VALUE edges are the graph traversal.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ValueSet'], 'in_subset': ['HashSubset']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Rule', 'Transform'],
         'in_subset': ['HashSubset'],
         'slot_uri': 'skos:definition'} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Mapping']} })
    skos_mappings: Optional[list[Mapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts, or to other registry entities (align.py's computed correspondences).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })
    aliases: Optional[list[str]] = Field(default=None, description="""Alternate names/synonyms/abbreviations for this entity (e.g. \"lfp\" for \"local field potential\"), preserved from the source schema. Used as alignment evidence (align.py's alias_overlap signal) — not part of the schema's own semantics.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity'], 'slot_uri': 'skos:altLabel'} })


class UnitOfMeasure(ConfiguredBaseModel):
    """
    A structured unit of measure for a RegistryProperty, inlined (not its own content-addressed entity). Field names/slot_uri follow LinkML's own linkml:units module — defined locally rather than imported, since db.py's DDL generator reads meta_model.yaml's own classes directly and doesn't resolve LinkML imports (see git history for the import-vs- repeat discussion). LinkML's own alignment for units *is* QUDT/rdfs — there's no separate \"linkml:\" URI for these concepts to also target.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'db_inline': {'tag': 'db_inline', 'value': True}},
         'class_uri': 'qudt:Unit',
         'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    ucum_code: Optional[str] = Field(default=None, description="""UCUM (Unified Code for Units of Measure) code, e.g. \"mV\", \"deg\", \"Hz\". Compact and machine-parseable — the primary field for programmatic unit-compatibility checks (align.py's unit veto).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnitOfMeasure'], 'slot_uri': 'qudt:ucumCode'} })
    has_quantity_kind: Optional[str] = Field(default=None, description="""IRI naming the dimension/kind of quantity being measured, e.g. a QUDT quantity-kind IRI for \"ElectricPotential\" or \"PlaneAngle\". Lets incommensurable units (different quantity kinds) be vetoed outright, independent of whether a conversion factor is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnitOfMeasure'], 'slot_uri': 'qudt:hasQuantityKind'} })
    symbol: Optional[str] = Field(default=None, description="""Name of the unit encoded as a symbol (e.g. \"Ω\", \"°\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnitOfMeasure'], 'slot_uri': 'qudt:symbol'} })
    abbreviation: Optional[str] = Field(default=None, description="""Short ASCII abbreviation for the unit, for contexts where non-ASCII symbols would be problematic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnitOfMeasure'], 'slot_uri': 'qudt:abbreviation'} })
    descriptive_name: Optional[str] = Field(default=None, description="""The spelled-out name of the unit, e.g. \"millivolt\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['UnitOfMeasure'], 'slot_uri': 'rdfs:label'} })


class SchemaSource(ConfiguredBaseModel):
    """
    Registry record for a schema source (one node per ingested schema label). Tracks the source's IRI, MIME type, and the registry version it was first added under. Identity uses id (not hash_id) because this is a mutable administrative record, not a content-addressed entity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    id: str = Field(default=..., description="""Plain unique identifier, used by every class that isn't part of the content-addressed RegistryEntity family (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping) — LinkML's own conventional name for a non-content-derived identifier. hash_id is reserved for RegistryEntity subclasses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry',
                       'Mapping',
                       'SchemaSource',
                       'SchemaVersionSnapshot']} })
    label: str = Field(default=..., description="""Short identifier label for this schema source (e.g. \"bids\", \"nwb\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    title: Optional[str] = Field(default=None, description="""Human-readable full name of the schema (e.g. \"Brain Imaging Data Structure\"), distinct from the short `label` used as its identifier.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    publisher: Optional[str] = Field(default=None, description="""Organization or group that maintains this schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    contact: Optional[str] = Field(default=None, description="""Contact point for this schema (person, mailing list, or URL).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    homepage: Optional[str] = Field(default=None, description="""Documentation or landing page for this schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    is_hub: Optional[bool] = Field(default=False, description="""True if this schema is (part of) the registry's core/bridge vocabulary that other schemas are matched against, rather than matching every schema pairwise. Not auto-derived — set deliberately, since which schema serves as the hub is a curatorial decision.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource'], 'ifabsent': 'false'} })
    source_iri: Optional[str] = Field(default=None, description="""Canonical IRI for this schema source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    source_version: Optional[str] = Field(default=None, description="""Semantic version of the schema at the time of ingestion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    mime_type: Optional[str] = Field(default=None, description="""MIME type of the schema file (e.g. \"application/yaml\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    created_at: Optional[datetime ] = Field(default=None, description="""ISO-8601 timestamp when this record was created.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself. No PROV-O term — purely our own versioning concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })


class SchemaVersionSnapshot(ConfiguredBaseModel):
    """
    An immutable snapshot of a schema at a specific version, created each time a schema ingestion produces new or changed content. Records the class and property counts and a human-readable summary of changes.
    QUESTIONABLE (as of 2026-08-04): likely unnecessary. It's write-only — nothing outside ingest_linkml.py's own _prev_schema_version() ever reads it back (not export_json.py, not mcp_server.py, not any CI workflow). Its source_version is a self-invented semver bump (_bump_semver()) that, after the first ingestion, ignores the source file's real declared meta[\"version\"] entirely — and it duplicates SchemaSource.source_version, which has its own bug (frozen at first-ingestion value, never updated). The one thing it enables (the \"schema unchanged, skip\" short-circuit) doesn't need stored history: write_registry_entities() is already idempotent, so stats (classes_new/properties_new/provenance_added) tell you the same thing fresh on every run. Added incidentally in a1dba23 (\"Auto-sync graph schema from meta_model.yaml via CI\"), not from a deliberate versioning design. Candidate for removal — same category as the Relation class (removed in c599c2b): present in the schema, never actually needed.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    id: str = Field(default=..., description="""Plain unique identifier, used by every class that isn't part of the content-addressed RegistryEntity family (ProvenanceEntry, SchemaSource, SchemaVersionSnapshot, Mapping) — LinkML's own conventional name for a non-content-derived identifier. hash_id is reserved for RegistryEntity subclasses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry',
                       'Mapping',
                       'SchemaSource',
                       'SchemaVersionSnapshot']} })
    schema_label: str = Field(default=..., description="""Label of the schema this snapshot belongs to (FK to SchemaSource.label).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    source_version: Optional[str] = Field(default=None, description="""Semantic version of the schema at the time of ingestion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    yml_path: Optional[str] = Field(default=None, description="""Relative path to the schema YAML file at snapshot time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    class_count: Optional[int] = Field(default=None, description="""Number of classes in the schema at this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    property_count: Optional[int] = Field(default=None, description="""Number of properties in the schema at this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    changes_summary: Optional[str] = Field(default=None, description="""Human-readable summary of what changed in this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    created_at: Optional[datetime ] = Field(default=None, description="""ISO-8601 timestamp when this record was created.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself. No PROV-O term — purely our own versioning concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
RegistryEntity.model_rebuild()
RegistryClass.model_rebuild()
RegistryProperty.model_rebuild()
ProvenanceEntry.model_rebuild()
MappingProvenanceEntry.model_rebuild()
Mapping.model_rebuild()
Rule.model_rebuild()
Transform.model_rebuild()
PermissibleValue.model_rebuild()
ValueSet.model_rebuild()
UnitOfMeasure.model_rebuild()
SchemaSource.model_rebuild()
SchemaVersionSnapshot.model_rebuild()
