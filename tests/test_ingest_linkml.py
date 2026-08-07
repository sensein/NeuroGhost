from pathlib import Path

import pytest

from ingest_linkml import parse_linkml, build_registry_entities
from schema_registry_utils import (
    RegistryProperty, RegistryClass, ValueSet, PermissibleValue, compute_hash_id_for,
)

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
                "aliases": [],
            },
            "Entity": {
                "iri": "https://example.org/schema#Entity",
                "definition": "Abstract base for all registry entities.",
                "is_a": None,
                "is_abstract": True,
                "slots": ["name"],
                "aliases": [],
            },
            "Person": {
                "iri": "https://schema.org/Person",
                "definition": "A research investigator.",
                "is_a": "Entity",
                "is_abstract": False,
                "slots": ["orcid", "role", "created_at", "name"],
                "aliases": ["Investigator"],
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
                "aliases": [],
            },
            "name": {
                "iri": "https://schema.org/name",
                "definition": "Full name.",
                "value_range": "xsd:string",
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": "",
                "aliases": [],
            },
            "orcid": {
                "iri": "https://example.org/schema#orcid",
                "definition": "ORCID identifier.",
                "value_range": "xsd:string",
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": r"^\d{4}-\d{4}-\d{4}-\d{3}[0-9X]$",
                "aliases": ["ORCID iD"],
            },
            "role": {
                "iri": "",
                "definition": "Role on the study (units: FTE)",
                "value_range": "xsd:string",
                "units": "FTE",
                "multivalued": True,
                "required": True,
                "pattern": "^[A-Za-z ]+$",
                "aliases": [],
            },
        },
        "enums": {},
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


def test_aliases_do_not_affect_identity():
    """
    aliases isn't tagged in_subset: HashSubset in meta_model.yaml, so
    it's excluded from hash_id — like class_uri/slot_uri, it's alternate-name
    metadata a source happens to supply, not part of what the entity *is*.
    Two otherwise-identical properties with different aliases must still
    collapse to the same hash_id.
    """
    base = dict(
        name="orcid", description="ORCID identifier.", range="xsd:string",
        unit=None, slot_uri="https://example.org/schema#orcid", skos_mappings=[],
    )
    with_alias = compute_hash_id_for(RegistryProperty, dict(base, aliases=["ORCID iD"]))
    without_alias = compute_hash_id_for(RegistryProperty, dict(base, aliases=[]))
    assert with_alias == without_alias


def test_build_registry_entities_produces_exactly_the_expected_objects():
    """
    Exact-equality check of build_registry_entities()'s output — the step
    that turns parse_linkml()'s dict into content-hashed RegistryProperty/
    RegistryClass instances. hash_id is a pure content hash (no randomness),
    so these values are reproducible; if the hash computation, the set of
    fields carried into the model, or the is_a/properties resolution ever
    changes, this fails.

    provenance is checked separately (excluded from the equality dump) since
    ProvenanceEntry.id/generated_at_time are non-deterministic per run.
    """
    parsed = parse_linkml(FIXTURES / "comprehensive.yml")
    properties, registry_classes, value_sets, permissible_values = build_registry_entities(
        parsed, "comprehensive", "tester"
    )
    assert value_sets == {}  # comprehensive.yml has no enums
    assert permissible_values == {}

    assert set(properties) == {"name", "orcid", "role", "created_at"}
    assert set(registry_classes) == {"Timestamped", "Entity", "Person"}

    for entity in (*properties.values(), *registry_classes.values()):
        assert len(entity.provenance) == 1
        prov = entity.provenance[0]
        assert prov.had_primary_source == "comprehensive"
        assert prov.was_attributed_to == "tester"
        assert prov.was_generated_by == "ingestion"
        assert prov.was_derived_from == []

    assert {
        name: p.model_dump(exclude={"provenance"})
        for name, p in properties.items()
    } == {
        "name": {
            "hash_id": "sha256:591db40aa8cac49437c2adca56ca7f734976241cc72859ce654bc5716caf1678",
            "name": "name",
            "description": "Full name.",
            "skos_mappings": [],
            "slot_uri": "https://schema.org/name",
            "range": "xsd:string",
            "unit": None,
            "aliases": [],
        },
        "orcid": {
            "hash_id": "sha256:c377472201ddeaae9d134cda4b3f8726a4cc416c8e736aba19670c2386c1d3e9",
            "name": "orcid",
            "description": "ORCID identifier.",
            "skos_mappings": [],
            "slot_uri": "https://example.org/schema#orcid",
            "range": "xsd:string",
            "unit": None,
            "aliases": ["ORCID iD"],
        },
        "role": {
            "hash_id": "sha256:a0f8b43c330c5213f158a2c1784bd9b9a79f503cc58b8c13e3622dd7e0f9a6ce",
            "name": "role",
            "description": "Role on the study (units: FTE)",
            "skos_mappings": [],
            "slot_uri": None,
            "range": "xsd:string",
            "unit": {
                "ucum_code": "FTE",
                "has_quantity_kind": None,
                "symbol": None,
                "abbreviation": None,
                "descriptive_name": None,
            },
            "aliases": [],
        },
        "created_at": {
            "hash_id": "sha256:db3db97594d0c015588b5f54fac4e8b0f6523232fbebe55ded2ef5e53b01bc5b",
            "name": "created_at",
            "description": "",
            "skos_mappings": [],
            "slot_uri": None,
            "range": "xsd:dateTime",
            "unit": None,
            "aliases": [],
        },
    }

    assert {
        name: c.model_dump(exclude={"provenance"})
        for name, c in registry_classes.items()
    } == {
        "Timestamped": {
            "hash_id": "sha256:1cb9a83caefddee4642eb1bd4592e300be9f11d9f41632fe3d02fd27ee160871",
            "name": "Timestamped",
            "description": "Mixin providing a creation timestamp.",
            "skos_mappings": [],
            "class_uri": None,
            "abstract": False,
            "properties": ["sha256:db3db97594d0c015588b5f54fac4e8b0f6523232fbebe55ded2ef5e53b01bc5b"],
            "is_a": None,
            "mixins": [],
            "aliases": [],
        },
        "Entity": {
            "hash_id": "sha256:3ae55de6930176ed27c54e63fcec01326e30df325a3040fec04c545e712e3f08",
            "name": "Entity",
            "description": "Abstract base for all registry entities.",
            "skos_mappings": [],
            "class_uri": "https://example.org/schema#Entity",
            "abstract": True,
            "properties": ["sha256:591db40aa8cac49437c2adca56ca7f734976241cc72859ce654bc5716caf1678"],
            "is_a": None,
            "mixins": [],
            "aliases": [],
        },
        "Person": {
            "hash_id": "sha256:d4ff9cbb35fb45296adf35c5e7e0c1fc45e4ac835120a699c3d6749536475487",
            "name": "Person",
            "description": "A research investigator.",
            "skos_mappings": [],
            "class_uri": "https://schema.org/Person",
            "abstract": False,
            "properties": [
                "sha256:591db40aa8cac49437c2adca56ca7f734976241cc72859ce654bc5716caf1678",
                "sha256:a0f8b43c330c5213f158a2c1784bd9b9a79f503cc58b8c13e3622dd7e0f9a6ce",
                "sha256:c377472201ddeaae9d134cda4b3f8726a4cc416c8e736aba19670c2386c1d3e9",
                "sha256:db3db97594d0c015588b5f54fac4e8b0f6523232fbebe55ded2ef5e53b01bc5b",
            ],
            "is_a": "sha256:3ae55de6930176ed27c54e63fcec01326e30df325a3040fec04c545e712e3f08",
            "mixins": [],
            "aliases": ["Investigator"],
        },
    }


def test_parse_linkml_extracts_enums():
    """parse_linkml() returns an 'enums' dict with parsed enum definitions."""
    parsed = parse_linkml(FIXTURES / "schema_with_enums.yml")

    assert "enums" in parsed
    assert "StatusEnum" in parsed["enums"]

    status_enum = parsed["enums"]["StatusEnum"]
    assert status_enum["definition"] == "Possible statuses for an annotation."
    assert set(status_enum["permissible_values"]) == {"active", "deprecated"}
    assert status_enum["permissible_values"]["active"]["meaning"] == (
        "http://www.w3.org/2004/02/skos/core#Concept"
    )
    assert status_enum["permissible_values"]["deprecated"]["meaning"] == ""


def test_build_registry_entities_produces_value_sets():
    """
    build_registry_entities()'s 3rd/4th return values are ValueSet and
    PermissibleValue dicts. PermissibleValue is a real RegistryEntity now
    (not the old hand-rolled node) — it gets a real description and
    provenance, keyed by hash_id since it's shared across enums/sources
    rather than tied to one source name.
    """
    parsed = parse_linkml(FIXTURES / "schema_with_enums.yml")
    properties, registry_classes, value_sets, permissible_values = build_registry_entities(
        parsed, "enum_test", "tester"
    )

    assert "StatusEnum" in value_sets
    vs = value_sets["StatusEnum"]
    assert isinstance(vs, ValueSet)
    assert vs.name == "StatusEnum"
    assert vs.description == "Possible statuses for an annotation."
    assert len(vs.permissible_values) == 2
    # hash_ids are deterministic — check they are sha256: prefixes
    for hid in vs.permissible_values:
        assert hid.startswith("sha256:")
    # Provenance from the ingestion
    assert len(vs.provenance) == 1
    assert vs.provenance[0].had_primary_source == "enum_test"

    assert set(vs.permissible_values) == set(permissible_values)
    for pv in permissible_values.values():
        assert isinstance(pv, PermissibleValue)
        assert pv.name in ("active", "deprecated")
        assert len(pv.provenance) == 1
        assert pv.provenance[0].had_primary_source == "enum_test"
