from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SkosMappingTypeEnum(str, Enum):
    EXACT_MATCH   = "EXACT_MATCH"
    CLOSE_MATCH   = "CLOSE_MATCH"
    BROAD_MATCH   = "BROAD_MATCH"
    NARROW_MATCH  = "NARROW_MATCH"
    RELATED_MATCH = "RELATED_MATCH"


class ProvenanceEntry(BaseModel):
    """One source's attestation of a registry entity (W3C PROV-O fields)."""
    uid:                Optional[str]  = None
    source:             str
    source_description: Optional[str] = None
    registry_version:   Optional[str]  = None
    generated_at:       datetime                # prov:generatedAtTime
    attributed_to:      str                      # prov:wasAttributedTo
    activity:           Optional[str]  = None    # prov:wasGeneratedBy
    derived_from:       List[str]      = Field(default_factory=list)  # prov:wasDerivedFrom


class SkosMapping(BaseModel):
    hash_id:      Optional[str]                  = None
    mapping_type: Optional[SkosMappingTypeEnum]  = None
    target:       Optional[str]                  = None


class Relation(BaseModel):
    hash_id:    Optional[str]              = None
    subject:    str
    predicate:  str
    object:     str
    provenance: List[ProvenanceEntry]      = Field(min_length=1)


class RegistryEntity(BaseModel):
    hash_id:      Optional[str]            = None
    name:         str
    description:  str
    provenance:   List[ProvenanceEntry]    = Field(min_length=1)
    skos_mappings: List[SkosMapping]       = Field(default_factory=list)


class RegistryClass(RegistryEntity):
    class_uri:        Optional[str]  = None
    abstract:         bool           = False
    # Stored as hash_id references; graph edges (HAS_PROPERTY, HAS_RELATION,
    # MIXIN) are the traversal mechanism — these lists mirror them for hashing.
    properties:   List[str]          = Field(default_factory=list)
    relations:    List[str]          = Field(default_factory=list)
    is_a:         Optional[str]      = None
    mixins:       List[str]          = Field(default_factory=list)


class RegistryProperty(RegistryEntity):
    slot_uri:         Optional[str]  = None
    range:            str
    units:            Optional[str]  = None
