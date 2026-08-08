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
                  'screg': {'prefix_prefix': 'screg',
                            'prefix_reference': 'https://example.org/schema-registry-utils/'},
                  'skos': {'prefix_prefix': 'skos',
                           'prefix_reference': 'http://www.w3.org/2004/02/skos/core#'}},
     'source_file': 'schemas/meta_model.yaml'} )

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



class RegistryEntity(ConfiguredBaseModel):
    """
    Common base for content-addressed, provenance-tracked objects registered in the schema registry. Identity (hash_id) is derived from content, so there is no separate version slot: a change produces a new hash_id, with lineage tracked via derived_from on each ProvenanceEntry.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })
    skos_mappings: Optional[list[SkosMapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })


class RegistryClass(RegistryEntity):
    """
    A registered class (object class) representing a concept or entity type in the registry, e.g. \"Patient\".
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    properties: Optional[list[str]] = Field(default=None, description="""The set of properties that belong to this class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass']} })
    relations: Optional[list[str]] = Field(default=None, description="""Directed relations from this class to other registry entities.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass']} })
    is_a: Optional[str] = Field(default=None, description="""The class this class inherits from (stored as hash_id FK).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass']} })
    mixins: Optional[list[str]] = Field(default=None, description="""Additional classes mixed into this class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass']} })
    class_uri: Optional[str] = Field(default=None, description="""Ontology IRI for this class, preserved from the source schema on ingestion. Not part of the content hash; used for alignment and cross-source lookup.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass']} })
    abstract: Optional[bool] = Field(default=False, description="""Whether this registered class is itself declared abstract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryClass'], 'ifabsent': 'false'} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })
    skos_mappings: Optional[list[SkosMapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })


class RegistryProperty(RegistryEntity):
    """
    A registered property (data element) representing a characteristic or attribute that can be attached to a RegistryClass, e.g. \"age\". Usage constraints (required, multivalued, min/max, pattern) are deliberately not here — they belong on Rule, since the same property can be required in one source's usage and optional in another's without being a different concept.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    range: str = Field(default=..., description="""The data type or value range for this property (e.g. a primitive type name such as \"string\" or \"integer\", or the hash_id of a ValueSet for enumerated values).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty']} })
    units: Optional[str] = Field(default=None, description="""Unit of measure for this property's values, if applicable.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty']} })
    slot_uri: Optional[str] = Field(default=None, description="""Ontology IRI for this property, preserved from the source schema on ingestion. Not part of the content hash; used for alignment and cross-source lookup.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryProperty']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })
    skos_mappings: Optional[list[SkosMapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })


class ProvenanceEntry(ConfiguredBaseModel):
    """
    One source's attestation of a registry entity — where it came from and how/when this record was generated (W3C PROV-O fields). An entity accumulates one ProvenanceEntry per source that attests to it; identity (hash_id) never depends on provenance, so the same entity can carry many. Stored as its own node, linked via HAS_PROVENANCE / HAS_PROVENANCE_P edges (multivalued — cannot be inlined into the parent's node table). Identified by uid, not hash_id — a ProvenanceEntry is a per-attestation record, not a deduplicated, content-addressed registry entity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    uid: str = Field(default=..., description="""Random unique identifier for this ProvenanceEntry record (not content-derived — a per-attestation record, not a deduplicated entity).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    source: str = Field(default=..., description="""Label of the source schema this attestation came from, e.g. \"bids\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry']} })
    source_description: Optional[str] = Field(default=None, description="""This source's own description text for the entity, if it differs from the entity's merged description.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    generated_at: datetime  = Field(default=..., description="""ISO-8601 timestamp this ProvenanceEntry was generated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:generatedAtTime'} })
    attributed_to: str = Field(default=..., description="""Agent (user or system) that generated this ProvenanceEntry.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasAttributedTo'} })
    activity: Optional[str] = Field(default=None, description="""The activity that produced this ProvenanceEntry, e.g. \"ingestion\", \"manual\", \"alignment\".""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry'], 'slot_uri': 'prov:wasGeneratedBy'} })
    derived_from: Optional[list[str]] = Field(default=None, description="""hash_ids of entities this entity was derived from, if any. Stored as a JSON-encoded string array in the graph database.""", json_schema_extra = { "linkml_meta": {'annotations': {'db_json': {'tag': 'db_json', 'value': True}},
         'domain_of': ['ProvenanceEntry'],
         'slot_uri': 'prov:wasDerivedFrom'} })


class SkosMapping(ConfiguredBaseModel):
    """
    A semantic mapping from a registry entity to an external vocabulary concept (SKOS mapping relation). Stored as its own node and linked via HAS_SKOS_MAPPING / HAS_SKOS_MAPPING_P edges.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    mapping_type: Optional[SkosMappingTypeEnum] = Field(default=None, description="""The kind of SKOS mapping relation this represents.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SkosMapping']} })
    target: Optional[str] = Field(default=None, description="""The external concept this mapping points to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SkosMapping']} })


class Relation(ConfiguredBaseModel):
    """
    A directed relationship between two registry entities (classes or properties), with its own content-addressed identity and provenance.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    subject: str = Field(default=..., description="""hash_id of the entity this relation points from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Relation']} })
    predicate: str = Field(default=..., description="""The type of relationship (e.g. isPartOf, isSimilarTo, isDerivedFrom).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Relation']} })
    object: str = Field(default=..., description="""hash_id of the entity this relation points to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Relation']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })


class Rule(RegistryEntity):
    """
    A validation/usage constraint that applies to a specific RegistryProperty (classes are a possible future extension) — required, multivalued, pattern, numeric bounds, or (when those aren't expressive enough) an arbitrary Python function. These don't live on RegistryProperty itself because they vary by usage: the same \"age\" property can be required in one source's schema and optional in another's, without being a different concept. A Rule is content- addressed like any other entity — the same constraints on the same property from two sources collapse to one Rule with two ProvenanceEntry records, exactly like RegistryProperty does.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    applies_to: str = Field(default=..., description="""The RegistryProperty this rule constrains (stored as hash_id FK, same pattern as is_a). Part of the content hash — a rule is defined by both its constraints and which property they apply to, so identical constraints on two different properties are different rules.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    required: Optional[bool] = Field(default=False, description="""Whether the property must be present.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule'], 'ifabsent': 'false'} })
    multivalued: Optional[bool] = Field(default=False, description="""Whether the property can hold multiple values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule'], 'ifabsent': 'false'} })
    pattern: Optional[str] = Field(default=None, description="""Regular expression the property's value must match.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    minimum_value: Optional[float] = Field(default=None, description="""Minimum permitted numeric value, if the property is numeric.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    maximum_value: Optional[float] = Field(default=None, description="""Maximum permitted numeric value, if the property is numeric.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    function_body: Optional[str] = Field(default=None, description="""Python source implementing custom validation logic, for constraints the declarative fields above (required/multivalued/pattern/min/max) can't express. Stored as plain text, like `pattern` — a Rule's identity is still a plain content hash, with no dependency on code existing elsewhere. Not executed by anything in this codebase yet; this only adds the ability to save it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })
    skos_mappings: Optional[list[SkosMapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })


class Transform(ConfiguredBaseModel):
    """
    STUB — a transformation between two RegistryClass definitions. Slots intentionally minimal; scope TBD.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })


class PermissibleValue(ConfiguredBaseModel):
    """
    A single permissible value within a ValueSet enumeration. The `name` field holds the value text (e.g. \"EXACT_MATCH\"); `meaning` optionally maps it to an external ontology IRI. Identity is content-addressed on (name, meaning) — identical values across sources share one node.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    meaning: Optional[str] = Field(default=None, description="""Ontology IRI this permissible value maps to (e.g. skos:exactMatch for the EXACT_MATCH value in SkosMappingTypeEnum).""", json_schema_extra = { "linkml_meta": {'domain_of': ['PermissibleValue']} })


class ValueSet(RegistryEntity):
    """
    A controlled set of permissible values, usable as a RegistryProperty range. LinkML enums ingest as ValueSet nodes; each permissible value becomes a separate PermissibleValue node linked via HAS_PERMISSIBLE_VALUE edges.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    permissible_values: Optional[list[str]] = Field(default=None, description="""The set of permissible values for this ValueSet. Stored as hash_id references; HAS_PERMISSIBLE_VALUE edges are the graph traversal.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ValueSet']} })
    hash_id: str = Field(default=..., description="""Content-hash-derived identifier (format sha256:<hex>). A change in any identity-defining field produces a new hash_id; lineage is preserved via derived_from.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity',
                       'SkosMapping',
                       'Relation',
                       'Transform',
                       'PermissibleValue']} })
    name: str = Field(default=..., description="""Human-readable label for this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform', 'PermissibleValue']} })
    description: str = Field(default=..., description="""Human-readable description of this entity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Transform']} })
    provenance: list[ProvenanceEntry] = Field(default=..., description="""One ProvenanceEntry per source attesting to this entity. Accumulates as more sources are ingested — never affects hash_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity', 'Relation']} })
    skos_mappings: Optional[list[SkosMapping]] = Field(default=None, description="""Semantic mappings to external vocabulary concepts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RegistryEntity']} })


class SchemaSource(ConfiguredBaseModel):
    """
    Registry record for a schema source (one node per ingested schema label). Tracks the source's IRI, MIME type, and the registry version it was first added under. Identity uses uid (not hash_id) because this is a mutable administrative record, not a content-addressed entity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    uid: str = Field(default=..., description="""Random unique identifier for this ProvenanceEntry record (not content-derived — a per-attestation record, not a deduplicated entity).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    label: str = Field(default=..., description="""Short identifier label for this schema source (e.g. \"bids\", \"nwb\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    source_iri: Optional[str] = Field(default=None, description="""Canonical IRI for this schema source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    source_version: Optional[str] = Field(default=None, description="""Semantic version of the schema at the time of ingestion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    mime_type: Optional[str] = Field(default=None, description="""MIME type of the schema file (e.g. \"application/yaml\").""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource']} })
    created_at: Optional[datetime ] = Field(default=None, description="""ISO-8601 timestamp when this record was created.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })


class SchemaVersionSnapshot(ConfiguredBaseModel):
    """
    An immutable snapshot of a schema at a specific version, created each time a schema ingestion produces new or changed content. Records the class and property counts and a human-readable summary of changes.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://example.org/schema-registry-utils/meta-model'})

    uid: str = Field(default=..., description="""Random unique identifier for this ProvenanceEntry record (not content-derived — a per-attestation record, not a deduplicated entity).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })
    schema_label: str = Field(default=..., description="""Label of the schema this snapshot belongs to (FK to SchemaSource.label).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    source_version: Optional[str] = Field(default=None, description="""Semantic version of the schema at the time of ingestion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    yml_path: Optional[str] = Field(default=None, description="""Relative path to the schema YAML file at snapshot time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    class_count: Optional[int] = Field(default=None, description="""Number of classes in the schema at this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    property_count: Optional[int] = Field(default=None, description="""Number of properties in the schema at this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    changes_summary: Optional[str] = Field(default=None, description="""Human-readable summary of what changed in this version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaVersionSnapshot']} })
    created_at: Optional[datetime ] = Field(default=None, description="""ISO-8601 timestamp when this record was created.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaSource', 'SchemaVersionSnapshot']} })
    registry_version: Optional[str] = Field(default=None, description="""Registry snapshot version in effect when this ProvenanceEntry was generated. Not on RegistryClass/RegistryProperty directly — the same entity can be attested by different sources at different times, each under a different registry version, so it belongs on the per-source attestation, not the entity itself.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProvenanceEntry', 'SchemaSource', 'SchemaVersionSnapshot']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
RegistryEntity.model_rebuild()
RegistryClass.model_rebuild()
RegistryProperty.model_rebuild()
ProvenanceEntry.model_rebuild()
SkosMapping.model_rebuild()
Relation.model_rebuild()
Rule.model_rebuild()
Transform.model_rebuild()
PermissibleValue.model_rebuild()
ValueSet.model_rebuild()
SchemaSource.model_rebuild()
SchemaVersionSnapshot.model_rebuild()
