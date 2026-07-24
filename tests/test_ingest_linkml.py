from pathlib import Path

import pytest

from ingest_linkml import parse_linkml, build_registry_entities
from schema_registry_utils import RegistryProperty, RegistryClass

FIXTURES = Path(__file__).parent / "fixtures"


def test_class_with_slots():
    parsed = parse_linkml(FIXTURES / "valid_slots.yml")

    assert set(parsed["classes"]) == {"Person"}
    person = parsed["classes"]["Person"]
    assert person["iri"] == "https://example.org/schema#Person"
    assert set(person["slots"]) == {"name", "orcid"}

    assert set(parsed["slots"]) == {"name", "orcid"}
    assert parsed["slots"]["name"]["value_range"] == "xsd:string"
    assert parsed["slots"]["orcid"]["pattern"]


def test_class_with_attributes():
    parsed = parse_linkml(FIXTURES / "valid_attributes.yml")

    assert set(parsed["classes"]) == {"Device"}
    device = parsed["classes"]["Device"]
    assert set(device["slots"]) == {"manufacturer", "sampling_rate"}

    # attributes declared inline on a class must show up in the global
    # slots dict too — this is exactly what the old hand-rolled parser missed
    assert set(parsed["slots"]) == {"manufacturer", "sampling_rate"}
    assert parsed["slots"]["sampling_rate"]["required"] is True
    assert parsed["slots"]["sampling_rate"]["units"] == "Hz"


def test_undefined_slot_raises():
    with pytest.raises(ValueError, match="nonexistent_slot"):
        parse_linkml(FIXTURES / "invalid_undefined_slot.yml")


def test_parse_linkml_extracts_exactly_the_expected_dict():
    """
    Exact-equality check (not spot-checks) of parse_linkml()'s raw LinkML
    extraction — this is the intermediate dict, before build_registry_entities()
    converts it into RegistryProperty/RegistryClass. It legitimately includes
    multivalued/required/pattern, since those are genuinely part of a LinkML
    slot declaration — whether the *registry* keeps them is a separate
    question, covered by test_build_registry_entities_* below.

    Exercises every element parse_linkml must handle at once: a mixin, an
    abstract base, is_a inheritance, a top-level `slots:` reference, an
    inline `attributes:` declaration, class_uri/slot_uri resolved both from
    the schema's own `prefixes:` (ex:) and from the KNOWN_PREFIXES fallback
    (schema:), a slot with no class_uri/slot_uri at all, multivalued/
    required/pattern, and a units-in-description extraction. If parse_linkml
    starts silently dropping or adding fields, this fails — a spot-check on
    a couple of keys wouldn't.
    """
    parsed = parse_linkml(FIXTURES / "comprehensive.yml")

    assert parsed == {
        "meta": {
            "id": "https://example.org/comprehensive",
            "name": "comprehensive",
            "version": "1.0.0",
            "description": "A schema exercising every element parse_linkml must extract.",
        },
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "ex": "https://example.org/schema#",
        },
        "classes": {
            "Timestamped": {
                "iri": "",
                "definition": "Mixin providing a creation timestamp.",
                "is_a": None,
                "is_abstract": False,
                "slots": ["created_at"],
            },
            "Entity": {
                "iri": "https://example.org/schema#Entity",
                "definition": "Abstract base for all registry entities.",
                "is_a": None,
                "is_abstract": True,
                "slots": ["name"],
            },
            "Person": {
                "iri": "https://schema.org/Person",
                "definition": "A research investigator.",
                "is_a": "Entity",
                "is_abstract": False,
                "slots": ["orcid", "role", "created_at", "name"],
            },
        },
        "slots": {
            "created_at": {
                "iri": "",
                "definition": "",
                "value_range": "xsd:dateTime",
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": "",
            },
            "name": {
                "iri": "https://schema.org/name",
                "definition": "Full name.",
                "value_range": "xsd:string",
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": "",
            },
            "orcid": {
                "iri": "https://example.org/schema#orcid",
                "definition": "ORCID identifier.",
                "value_range": "xsd:string",
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": r"^\d{4}-\d{4}-\d{4}-\d{3}[0-9X]$",
            },
            "role": {
                "iri": "",
                "definition": "Role on the study (units: FTE)",
                "value_range": "xsd:string",
                "units": "FTE",
                "multivalued": True,
                "required": True,
                "pattern": "^[A-Za-z ]+$",
            },
        },
    }


def test_registry_property_does_not_retain_usage_constraints():
    """
    parse_linkml()'s dict has multivalued/required/pattern (see above) — but
    RegistryProperty deliberately doesn't model them at all (deferred to a
    future Rule, since the same property can be required in one source's
    usage and optional in another's without being a different concept).
    Assert this at the model level, not just "the dict I built doesn't have
    it" — if someone re-adds these fields to RegistryProperty, this fails.
    """
    for field in ("required", "multivalued", "pattern"):
        assert field not in RegistryProperty.model_fields


def test_build_registry_entities_produces_exactly_the_expected_objects():
    """
    Exact-equality check of build_registry_entities()'s output — the step
    that turns parse_linkml()'s dict into content-hashed RegistryProperty/
    RegistryClass instances. hash_id is a pure content hash (no randomness),
    so these values are reproducible; if the hash computation, the set of
    fields carried into the model, or the is_a/properties resolution ever
    changes, this fails.

    provenance is checked separately (excluded from the equality dump) since
    ProvenanceEntry.uid/generated_at are non-deterministic per run.
    """
    parsed = parse_linkml(FIXTURES / "comprehensive.yml")
    properties, registry_classes = build_registry_entities(parsed, "comprehensive", "tester")

    assert set(properties) == {"name", "orcid", "role", "created_at"}
    assert set(registry_classes) == {"Timestamped", "Entity", "Person"}

    for entity in (*properties.values(), *registry_classes.values()):
        assert len(entity.provenance) == 1
        prov = entity.provenance[0]
        assert prov.source == "comprehensive"
        assert prov.attributed_to == "tester"
        assert prov.activity == "ingestion"
        assert prov.derived_from == []

    assert {
        name: p.model_dump(exclude={"provenance"})
        for name, p in properties.items()
    } == {
        "name": {
            "hash_id": "sha256:86057d0532a7584c9e69bd48e0129cc8bc37dfa78448e832d3373ed3ac404b43",
            "name": "name",
            "description": "Full name.",
            "skos_mappings": [],
            "slot_uri": "https://schema.org/name",
            "range": "xsd:string",
            "units": None,
        },
        "orcid": {
            "hash_id": "sha256:8bddfe8f326dab2077cd95446fa63eb7708cab8c096adc2ad53979d91b73862d",
            "name": "orcid",
            "description": "ORCID identifier.",
            "skos_mappings": [],
            "slot_uri": "https://example.org/schema#orcid",
            "range": "xsd:string",
            "units": None,
        },
        "role": {
            "hash_id": "sha256:b401d00ccb63e9accb3a1e2360a2f5d6997c21ae205324cf58ddd72712ce1538",
            "name": "role",
            "description": "Role on the study (units: FTE)",
            "skos_mappings": [],
            "slot_uri": None,
            "range": "xsd:string",
            "units": "FTE",
        },
        "created_at": {
            "hash_id": "sha256:cec09ed2e03b1e39519b3dffbc5444bebe5f36dc89dd17b3faf4f32cea00c289",
            "name": "created_at",
            "description": "",
            "skos_mappings": [],
            "slot_uri": None,
            "range": "xsd:dateTime",
            "units": None,
        },
    }

    assert {
        name: c.model_dump(exclude={"provenance"})
        for name, c in registry_classes.items()
    } == {
        "Timestamped": {
            "hash_id": "sha256:fa51878510090a0a42be142fc4552fd5ce39b115646022aa5eb792e6667d2b47",
            "name": "Timestamped",
            "description": "Mixin providing a creation timestamp.",
            "skos_mappings": [],
            "class_uri": None,
            "abstract": False,
            "properties": ["sha256:cec09ed2e03b1e39519b3dffbc5444bebe5f36dc89dd17b3faf4f32cea00c289"],
            "relations": [],
            "is_a": None,
            "mixins": [],
        },
        "Entity": {
            "hash_id": "sha256:a5f7bcf3d61d1b1bf7aaee30af3a77d52373a7267a6a40b739b1d8db7644453d",
            "name": "Entity",
            "description": "Abstract base for all registry entities.",
            "skos_mappings": [],
            "class_uri": "https://example.org/schema#Entity",
            "abstract": True,
            "properties": ["sha256:86057d0532a7584c9e69bd48e0129cc8bc37dfa78448e832d3373ed3ac404b43"],
            "relations": [],
            "is_a": None,
            "mixins": [],
        },
        "Person": {
            "hash_id": "sha256:7dbfa717e2624b881589e5beac94e176424b606e75d0f35763cf0faa55cfc588",
            "name": "Person",
            "description": "A research investigator.",
            "skos_mappings": [],
            "class_uri": "https://schema.org/Person",
            "abstract": False,
            "properties": [
                "sha256:86057d0532a7584c9e69bd48e0129cc8bc37dfa78448e832d3373ed3ac404b43",
                "sha256:8bddfe8f326dab2077cd95446fa63eb7708cab8c096adc2ad53979d91b73862d",
                "sha256:b401d00ccb63e9accb3a1e2360a2f5d6997c21ae205324cf58ddd72712ce1538",
                "sha256:cec09ed2e03b1e39519b3dffbc5444bebe5f36dc89dd17b3faf4f32cea00c289",
            ],
            "relations": [],
            "is_a": "sha256:a5f7bcf3d61d1b1bf7aaee30af3a77d52373a7267a6a40b739b1d8db7644453d",
            "mixins": [],
        },
    }
