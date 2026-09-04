import pytest

from conftest import FIXTURES, is_uuid
from ingest_linkml import parse_linkml, build_registry_entities
from schema_registry_utils import (
    RegistryProperty, RegistryClass, RegistryValueSet, PermissibleValue, RegistryRule,
    compute_content_hash_for,
)


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
            "title": "",
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
                "is_mixin": True,
                "mixins": [],
                "slots": ["created_at"],
                "aliases": [],
            },
            "Entity": {
                "iri": "https://example.org/schema#Entity",
                "definition": "Abstract base for all registry entities.",
                "is_a": None,
                "is_abstract": True,
                "is_mixin": False,
                "mixins": [],
                "slots": ["name"],
                "aliases": [],
            },
            "Person": {
                "iri": "https://schema.org/Person",
                "definition": "A research investigator.",
                "is_a": "Entity",
                "is_abstract": False,
                "is_mixin": False,
                "mixins": ["Timestamped"],
                "slots": ["orcid", "role", "created_at", "name"],
                "aliases": ["Investigator"],
            },
        },
        "slots": {
            "created_at": {
                "iri": "",
                "definition": "",
                "value_range": ["xsd:dateTime"],
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": "",
                "minimum_value": None,
                "maximum_value": None,
                "aliases": [],
            },
            "name": {
                "iri": "https://schema.org/name",
                "definition": "Full name.",
                "value_range": ["xsd:string"],
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": "",
                "minimum_value": None,
                "maximum_value": None,
                "aliases": [],
            },
            "orcid": {
                "iri": "https://example.org/schema#orcid",
                "definition": "ORCID identifier.",
                "value_range": ["xsd:string"],
                "units": "",
                "multivalued": False,
                "required": False,
                "pattern": r"^\d{4}-\d{4}-\d{4}-\d{3}[0-9X]$",
                "minimum_value": None,
                "maximum_value": None,
                "aliases": ["ORCID iD"],
            },
            "role": {
                "iri": "",
                "definition": "Role on the study (units: FTE)",
                "value_range": ["xsd:string"],
                "units": "FTE",
                "multivalued": True,
                "required": True,
                "pattern": "^[A-Za-z ]+$",
                "minimum_value": None,
                "maximum_value": None,
                "aliases": [],
            },
        },
        "enums": {},
        "source_metadata": {},
    }


def test_registry_property_does_not_retain_usage_constraints():
    """
    parse_linkml()'s dict has multivalued/required/pattern (see above) — but
    RegistryProperty deliberately doesn't model them at all: they belong on
    RegistryRule instead (see test_build_registry_entities_maps_person_
    classes_properties_and_rules), since the same property can be required
    in one source's usage and optional in another's without being a
    different concept. Assert this at the model level, not just "the dict
    I built doesn't have it" — if someone re-adds these fields to
    RegistryProperty, this fails.
    """
    for field in ("required", "multivalued", "pattern"):
        assert field not in RegistryProperty.model_fields


def test_aliases_do_not_affect_identity():
    """
    aliases isn't tagged in_subset: HashSubset in meta_model.yaml, so
    it's excluded from sha256_hash — like class_uri/slot_uri, it's alternate-name
    metadata a source happens to supply, not part of what the entity *is*.
    Two otherwise-identical properties with different aliases must still
    collapse to the same sha256_hash (and therefore share an id via dedup).
    """
    base = dict(
        name="orcid", description="ORCID identifier.",
        concept_uri="https://example.org/schema#orcid",
        skos_mappings=[],
    )
    with_alias = compute_content_hash_for(RegistryProperty, dict(base, aliases=["ORCID iD"]))
    without_alias = compute_content_hash_for(RegistryProperty, dict(base, aliases=[]))
    assert with_alias == without_alias


def test_range_and_unit_live_on_rules_not_property_identity(tmp_path):
    """
    A RegistryProperty is a pure concept: its value type and unit are not part
    of its identity — they aren't even fields on the model. They live on RANGE
    / UNIT RegistryRules. So two schemas that type the same slot differently
    produce the SAME property (identical sha256_hash, so "age" collapses across
    schemas) while each source's type is preserved as its own RANGE rule. This
    is also what makes a self-referential range cycle-free: the class hash
    never depends on the range (see the bican_prov test).
    """
    for field in ("property_range", "range_any_of", "unit"):
        assert field not in RegistryProperty.model_fields

    def build(range_type):
        yml = tmp_path / f"s_{range_type}.yml"
        yml.write_text(
            "id: https://example.org/s\n"
            "name: s\n"
            "prefixes: {linkml: https://w3id.org/linkml/}\n"
            "default_range: string\n"
            "imports: [linkml:types]\n"
            "classes:\n"
            "  Person:\n"
            "    attributes:\n"
            "      age:\n"
            f"        range: {range_type}\n"
        )
        return build_registry_entities(parse_linkml(yml), "s", "tester")

    props_i, _, _, _, rules_i, _ = build("integer")
    props_s, _, _, _, rules_s, _ = build("string")

    # Same concept -> identical property identity (collapses across schemas).
    assert props_i["age"].sha256_hash == props_s["age"].sha256_hash

    def range_val(rules, prop):
        return next(r.rule_value for r in rules.values()
                    if r.rule_type == "RANGE" and r.applies_to == [prop.id])

    # ...but each source's type is preserved on its own RANGE rule.
    assert range_val(rules_i, props_i["age"]) == "xsd:integer"
    assert range_val(rules_s, props_s["age"]) == "xsd:string"


def test_union_range_becomes_several_range_rules(tmp_path):
    """
    A union / polymorphic property (LinkML `any_of`, JSON Schema `anyOf`) has
    more than one permitted range. There is no `range_any_of` and no separate
    rule_type: the property simply gets one RANGE rule per permitted type
    (each resolved to a real class/enum id), while a plain single-range
    property gets exactly one RANGE rule.
    """
    yml = tmp_path / "u.yml"
    yml.write_text(
        "id: https://example.org/u\n"
        "name: u\n"
        "prefixes: {linkml: https://w3id.org/linkml/}\n"
        "default_range: string\n"
        "imports: [linkml:types]\n"
        "classes:\n"
        "  Person: {attributes: {pname: {range: string}}}\n"
        "  Organization: {attributes: {oname: {range: string}}}\n"
        "  Doc:\n"
        "    attributes:\n"
        "      contributor:\n"
        "        multivalued: true\n"
        "        any_of: [{range: Person}, {range: Organization}]\n"
        "      title: {range: string}\n"
    )
    props, classes, _, _, rules, _ = build_registry_entities(parse_linkml(yml), "u", "tester")

    def range_vals(prop):
        return {r.rule_value for r in rules.values()
                if r.rule_type == "RANGE" and r.applies_to == [prop.id]}

    # union -> several RANGE rules, one per permitted class id
    assert range_vals(props["contributor"]) == {
        classes["Person"].id, classes["Organization"].id,
    }
    # plain single range -> exactly one RANGE rule
    assert range_vals(props["title"]) == {"xsd:string"}


# Deterministic sha256 fingerprints for the entities that come out of
# comprehensive.yml. Kept explicit so a silent shift in what feeds the hash
# (e.g. a HashSubset slot added/removed, or _digest's canonicalization
# changing) fails loudly here. UUIDs are non-deterministic (uuid4) so the
# `id` field is asserted structurally, and cross-refs are checked by matching
# them against the target entity's own id — see the test body.
EXPECTED_PROP_SHAS = {
    "name":       "sha256:6adbf60646df63f0b93a58a23e65fcbec14e2c1bd5ff0a2c2bff0a3b57824a5f",
    "orcid":      "sha256:83dffd6b0c49dc06459fc9d2e085ad772c2b8f12aa31ff4ba44986558482114c",
    "role":       "sha256:6b7c09ed421df77f2ae43dd36bebf20160c558ab7637667f66c31ae14b8ee389",
    "created_at": "sha256:29ba3a8a1b635cb529acfb42282e4f28b6fc069eecc7aa3564b8ddf7164e0061",
}
# Class sha256_hashes are deliberately NOT asserted with exact values: a
# class's content includes its properties' UUID ids (see meta_model's
# HashSubset on RegistryClass.properties), so the class hash is only
# deterministic if the property UUIDs are — which in production happens
# via dedup lookup on subsequent ingests, and in tests via the FakeConn
# helper below. See test_class_hash_dedup_makes_a_re_ingest_deterministic
# for the invariant that actually matters (second ingest with dedup
# produces the same ids as the first).


def test_build_registry_entities_produces_exactly_the_expected_objects():
    """
    Two-part check on build_registry_entities()'s output — the step that
    turns parse_linkml()'s dict into RegistryProperty/RegistryClass
    instances.

    1. sha256_hash is a pure content fingerprint, deterministic across runs,
       so it's asserted with exact expected values. If the hash computation,
       the set of fields carried into the model, or the is_a/properties
       resolution ever changes, this fails.
    2. id is a uuid4 (non-deterministic per run) — asserted structurally
       (parses as a UUID) and by cross-reference consistency: each class's
       parent_class and properties list must match the target entity's own
       id, so property/class UUIDs and their references stay wired up
       correctly regardless of what specific UUIDs get minted this run.

    provenance is checked separately (excluded from the equality dump) since
    ProvenanceEntry.id/generated_at_time are non-deterministic per run.
    """
    parsed = parse_linkml(FIXTURES / "comprehensive.yml")
    properties, registry_classes, value_sets, permissible_values, rules, provenance_entries = build_registry_entities(
        parsed, "comprehensive", "tester"
    )
    assert value_sets == {}  # comprehensive.yml has no enums
    assert permissible_values == {}

    assert set(properties) == {"name", "orcid", "role", "created_at"}
    assert set(registry_classes) == {"Timestamped", "Entity", "Person"}

    for entity in (*properties.values(), *registry_classes.values()):
        assert len(entity.provenance) == 1
        prov = provenance_entries[entity.provenance[0]]
        assert prov.had_primary_source == "comprehensive"
        assert prov.was_attributed_to == "tester"
        assert prov.was_generated_by == "ingestion"
        assert prov.was_derived_from == []

    # 1a. Property sha256_hashes are exactly what's expected.
    for name, prop in properties.items():
        assert prop.sha256_hash == EXPECTED_PROP_SHAS[name], name
        assert is_uuid(prop.id), f"{name}.id not a UUID: {prop.id}"

    # 1b. Property content dumps (excluding id/sha256_hash/provenance which
    #     are checked separately) are exactly the expected shape.
    non_identity_dump = {
        name: p.model_dump(exclude={"provenance", "id", "sha256_hash"})
        for name, p in properties.items()
    }
    # A property is a pure concept now: name + description + concept_uri +
    # aliases + skos_mappings. Value type and unit are NOT fields here — they
    # live on RANGE / UNIT rules (asserted below).
    assert non_identity_dump == {
        "name": {
            "name": "name",
            "description": "Full name.",
            "skos_mappings": [],
            "concept_uri": "https://schema.org/name",
            "aliases": [],
        },
        "orcid": {
            "name": "orcid",
            "description": "ORCID identifier.",
            "skos_mappings": [],
            "concept_uri": "https://example.org/schema#orcid",
            "aliases": ["ORCID iD"],
        },
        "role": {
            "name": "role",
            "description": "Role on the study (units: FTE)",
            "skos_mappings": [],
            "concept_uri": None,
            "aliases": [],
        },
        "created_at": {
            "name": "created_at",
            "description": "",
            "skos_mappings": [],
            "concept_uri": None,
            "aliases": [],
        },
    }

    # Value type + unit moved to rules: each property has a RANGE rule with
    # the right type, and `role` (units: FTE) additionally has a UNIT rule.
    def range_val(pname):
        vs = [r.rule_value for r in rules.values()
              if r.rule_type == "RANGE" and r.applies_to == [properties[pname].id]]
        return vs[0] if vs else None

    assert range_val("name") == "xsd:string"
    assert range_val("orcid") == "xsd:string"
    assert range_val("role") == "xsd:string"
    assert range_val("created_at") == "xsd:dateTime"

    unit_rules = [r for r in rules.values() if r.rule_type == "UNIT"]
    assert len(unit_rules) == 1
    assert unit_rules[0].rule_value == "FTE"
    assert unit_rules[0].applies_to == [properties["role"].id]

    # 2a. Every class carries a sha256_hash of the right shape and a valid
    #     UUID id. Exact class sha256 values aren't asserted — see the
    #     comment on EXPECTED_CLASS_SHAS above.
    for name, rc in registry_classes.items():
        assert rc.sha256_hash.startswith("sha256:"), name
        assert is_uuid(rc.id), f"{name}.id not a UUID: {rc.id}"

    # 2b. Class content dumps (excluding id/sha256_hash/provenance/properties/
    #     parent_class/class_mixins — the reference fields hold
    #     non-deterministic UUIDs verified separately below) are exactly
    #     the expected shape.
    class_dump = {
        name: c.model_dump(exclude={"provenance", "id", "sha256_hash",
                                    "properties", "parent_class", "class_mixins"})
        for name, c in registry_classes.items()
    }
    assert class_dump == {
        "Timestamped": {
            "name": "Timestamped",
            "description": "Mixin providing a creation timestamp.",
            "skos_mappings": [],
            "concept_uri": None,
            "is_abstract": False,
            "is_mixin": True,
            "aliases": [],
        },
        "Entity": {
            "name": "Entity",
            "description": "Abstract base for all registry entities.",
            "skos_mappings": [],
            "concept_uri": "https://example.org/schema#Entity",
            "is_abstract": True,
            "is_mixin": False,
            "aliases": [],
        },
        "Person": {
            "name": "Person",
            "description": "A research investigator.",
            "skos_mappings": [],
            "concept_uri": "https://schema.org/Person",
            "is_abstract": False,
            "is_mixin": False,
            "aliases": ["Investigator"],
        },
    }

    # 3. Cross-reference wiring: Person is_a Entity, Person mixins
    #    Timestamped, and each class's properties list matches the target
    #    property ids.
    assert registry_classes["Person"].parent_class == registry_classes["Entity"].id
    assert registry_classes["Timestamped"].parent_class is None
    assert registry_classes["Entity"].parent_class is None

    assert registry_classes["Person"].class_mixins == sorted([registry_classes["Timestamped"].id])
    assert registry_classes["Timestamped"].class_mixins == []
    assert registry_classes["Entity"].class_mixins == []

    assert registry_classes["Timestamped"].properties == sorted([properties["created_at"].id])
    assert registry_classes["Entity"].properties == sorted([properties["name"].id])
    assert registry_classes["Person"].properties == sorted([
        properties["name"].id, properties["orcid"].id,
        properties["role"].id, properties["created_at"].id,
    ])


# See the comment on EXPECTED_PROP_SHAS above re: why property sha256_hashes
# are asserted exactly but class ones aren't.
EXPECTED_BICAN_PROP_SHAS = {
    "used":             "sha256:9f719f19b5b32ee5f8ce091ba22c4b0ef9bd414d1b2505861c8fe19538d61c29",
    "was_derived_from": "sha256:a756197b0fcf326f2fba79f9a14bb89ed365f9f2148233004d4b707ee1689a82",
    "was_generated_by": "sha256:27c82a095779eb2fb162c499d190a113e5b2b3f7c7593babc9edb9daf41447b5",
}


def test_build_registry_entities_maps_bican_prov_onto_the_meta_model():
    """
    Same check as test_build_registry_entities_produces_exactly_the_expected_objects,
    on bican_prov.yaml — this is the "mapping onto the meta-model" step:
    parse_linkml()'s raw LinkML dict (tested separately by
    test_parse_linkml_extracts_bican_prov_exactly) becomes real
    RegistryClass/RegistryProperty instances here.

    The interesting case this fixture exercises that comprehensive.yml
    doesn't: `used`'s range is `ProvEntity`, a class in the same schema, and
    `was_derived_from` on ProvEntity ranges over ProvEntity itself (a
    self-reference). Each range comes out as the target class's real id on a
    RANGE rule — proof that ranges resolve to real ids by the time this
    function returns. The self-reference is cycle-free precisely because range
    lives on a rule, not in the property/class hash: class hashes settle
    first, then the range rule points at the settled id.
    """
    parsed = parse_linkml(FIXTURES / "bican_prov.yaml")
    properties, registry_classes, value_sets, permissible_values, rules, provenance_entries = build_registry_entities(
        parsed, "bican_prov", "tester"
    )
    assert value_sets == {}
    assert permissible_values == {}

    assert set(properties) == {"used", "was_derived_from", "was_generated_by"}
    assert set(registry_classes) == {"ProvActivity", "ProvEntity"}

    for entity in (*properties.values(), *registry_classes.values()):
        assert len(entity.provenance) == 1
        prov = provenance_entries[entity.provenance[0]]
        assert prov.had_primary_source == "bican_prov"
        assert prov.was_attributed_to == "tester"
        assert prov.was_generated_by == "ingestion"
        assert prov.was_derived_from == []

    # Property sha256_hashes are exactly what's expected.
    for name, prop in properties.items():
        assert prop.sha256_hash == EXPECTED_BICAN_PROP_SHAS[name], name
        assert is_uuid(prop.id), f"{name}.id not a UUID: {prop.id}"

    # Both source classes declare `mixin: true` — is_mixin must carry
    # through, not silently default to False.
    for name, rc in registry_classes.items():
        assert rc.is_mixin is True, name
        assert rc.is_abstract is False, name

    # Each property's RANGE rule value must be the real class id, not the
    # synthetic make_iri("ProvEntity")-style placeholder parse_linkml() starts
    # with. was_derived_from -> ProvEntity is the self-reference.
    def range_val(pname):
        return next(r.rule_value for r in rules.values()
                    if r.rule_type == "RANGE" and r.applies_to == [properties[pname].id])

    assert range_val("used") == registry_classes["ProvEntity"].id
    assert range_val("was_derived_from") == registry_classes["ProvEntity"].id
    assert range_val("was_generated_by") == registry_classes["ProvActivity"].id

    # Cross-reference wiring: each class's properties list matches the
    # target property's own id.
    assert registry_classes["ProvActivity"].properties == [properties["used"].id]
    assert registry_classes["ProvEntity"].properties == sorted([
        properties["was_derived_from"].id, properties["was_generated_by"].id,
    ])


def test_class_hash_dedup_makes_a_re_ingest_deterministic(monkeypatch):
    """
    On a first ingest with an empty graph, every entity gets a fresh uuid4
    id — RegistryProperty ids are random, so any RegistryClass sha256 that
    includes those property ids is also non-deterministic across separate
    empty-graph runs.

    In production this is not a problem: the second ingest of the same
    schema (or any other schema that shares content) finds each entity by
    sha256_hash and reuses the existing id, so class content stabilizes and
    dedup collapses the class too. This test simulates that with a fake
    conn: after the first ingest, feed the entities' sha256 → id map back
    in as `find_id_by_sha256` results, run the second ingest, and assert
    every id round-trips.
    """
    import ingest_linkml as ingest_mod
    from ingest_linkml import build_registry_entities, parse_linkml

    parsed = parse_linkml(FIXTURES / "comprehensive.yml")
    props1, classes1, _, _, _, _ = build_registry_entities(parsed, "comprehensive", "tester")

    # After first ingest: build the (label, sha256) -> id map that a
    # populated registry would return from find_id_by_sha256.
    seen: dict[tuple[str, str], str] = {}
    for p in props1.values():
        seen[("RegistryProperty", p.sha256_hash)] = p.id
    for c in classes1.values():
        seen[("RegistryClass", c.sha256_hash)] = c.id

    def fake_lookup(conn, label, sha):
        return seen.get((label, sha))

    monkeypatch.setattr(ingest_mod, "find_id_by_sha256", fake_lookup)

    # Second ingest, this time with `conn` set to any non-None sentinel — the
    # patched find_id_by_sha256 doesn't touch it. Every id must match.
    props2, classes2, _, _, _, _ = build_registry_entities(
        parsed, "comprehensive", "tester", conn=object(),
    )
    for name, p1 in props1.items():
        assert props2[name].id == p1.id, name
        assert props2[name].sha256_hash == p1.sha256_hash, name
    for name, c1 in classes1.items():
        assert classes2[name].id == c1.id, name
        assert classes2[name].sha256_hash == c1.sha256_hash, name


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
    build_registry_entities()'s 3rd/4th return values are RegistryValueSet and
    PermissibleValue dicts. PermissibleValue is a real RegistryEntity now
    (not the old hand-rolled node) — it gets a real description and
    provenance, keyed by id since it's shared across enums/sources
    rather than tied to one source name.
    """
    parsed = parse_linkml(FIXTURES / "schema_with_enums.yml")
    properties, registry_classes, value_sets, permissible_values, rules, provenance_entries = build_registry_entities(
        parsed, "enum_test", "tester"
    )

    assert "StatusEnum" in value_sets
    vs = value_sets["StatusEnum"]
    assert isinstance(vs, RegistryValueSet)
    assert vs.name == "StatusEnum"
    assert vs.description == "Possible statuses for an annotation."
    assert len(vs.permissible_values) == 2
    # PermissibleValue references are UUIDs (the target's id).
    for pv_id in vs.permissible_values:
        assert is_uuid(pv_id)
    # sha256_hash on the value set itself starts with the sha256: prefix.
    assert vs.sha256_hash.startswith("sha256:")
    # Provenance from the ingestion
    assert len(vs.provenance) == 1
    assert provenance_entries[vs.provenance[0]].had_primary_source == "enum_test"

    assert set(vs.permissible_values) == set(permissible_values)
    for pv in permissible_values.values():
        assert isinstance(pv, PermissibleValue)
        assert pv.name in ("active", "deprecated")
        assert is_uuid(pv.id)
        assert pv.sha256_hash.startswith("sha256:")
        assert len(pv.provenance) == 1
        assert provenance_entries[pv.provenance[0]].had_primary_source == "enum_test"


EXPECTED_PERSON_PROP_SHAS = {
    "name":      "sha256:2c2e4f7e8f5a3c9544f13c767b5a97276ae42a07824facbf3c2243dbd260ca3a",
    "last_name": "sha256:b95bff4df00b30ea6ff596642c9d141aa6808dffff8acf4676cd2b327a98c895",
    "age":       "sha256:0bbe5ed5f5411f76cb97eda270069c1d5bea14f9ec767748e0a40730f6995011",
}


def test_build_registry_entities_maps_person_classes_properties_and_rules():
    """
    person.yml: one class (Person), three plain-scalar properties
    (name/last_name: string, age: integer), and four declared constraints —
    a pattern on `name`, `required: true` on `last_name`, minimum_value/
    maximum_value on `age` — the first real exercise of RegistryRule
    construction in build_registry_entities(). All at the
    build_registry_entities() stage: no DB involved, this is
    "did parse_linkml()'s dict get mapped onto the meta-model correctly,"
    not "did LinkML read the file correctly" (that's parse_linkml()'s own
    tests) and not "did it get written correctly" (that's
    test_ingest_registry.py, against a real graph).
    """
    parsed = parse_linkml(FIXTURES / "person.yml")
    properties, registry_classes, value_sets, permissible_values, rules, provenance_entries = (
        build_registry_entities(parsed, "person", "tester")
    )
    assert value_sets == {}
    assert permissible_values == {}

    # Classes
    assert set(registry_classes) == {"Person"}
    person = registry_classes["Person"]
    assert person.description == "An individual human being."
    assert person.is_abstract is False
    assert person.is_mixin is False

    # Properties
    assert set(properties) == {"name", "last_name", "age"}
    for name, prop in properties.items():
        assert prop.sha256_hash == EXPECTED_PERSON_PROP_SHAS[name], name
        assert is_uuid(prop.id), f"{name}.id not a UUID: {prop.id}"
    assert person.properties == sorted([
        properties["name"].id, properties["last_name"].id, properties["age"].id,
    ])

    # Rules — the actual point of this test. Every property gets a RANGE rule
    # carrying its value type (that's where the type lives now, not on the
    # property); plus the declared constraints: `name` (pattern), `last_name`
    # (required), and `age` (min + max value).
    #
    # sha256_hash isn't asserted with an exact value (same reasoning as
    # class sha256_hashes above): `applies_to` is in HashSubset and holds
    # a property's id, a freshly-minted UUID with no conn to dedup
    # against here, so it isn't deterministic across runs. Checked
    # structurally instead.
    assert set(rules) == {
        "name:RANGE", "last_name:RANGE", "age:RANGE",
        "name:PATTERN", "last_name:REQUIRED", "age:MIN_VALUE", "age:MAX_VALUE",
    }

    # RANGE rules carry the value type that used to live on property_range.
    assert rules["name:RANGE"].rule_value == "xsd:string"
    assert rules["name:RANGE"].applies_to == [properties["name"].id]
    assert rules["last_name:RANGE"].rule_value == "xsd:string"
    assert rules["age:RANGE"].rule_value == "xsd:integer"
    assert rules["age:RANGE"].applies_to == [properties["age"].id]
    for key, rule in rules.items():
        assert isinstance(rule, RegistryRule)
        assert rule.sha256_hash.startswith("sha256:"), key
        assert is_uuid(rule.id), f"{key}.id not a UUID: {rule.id}"
        assert rule.severity == "ERROR"
        assert rule.used_in_class is None
        assert rule.referenced_entities == []

    name_rule = rules["name:PATTERN"]
    assert name_rule.rule_type == "PATTERN"
    assert name_rule.rule_value == "^[A-Za-z ]+$"
    assert name_rule.applies_to == [properties["name"].id]

    last_name_rule = rules["last_name:REQUIRED"]
    assert last_name_rule.rule_type == "REQUIRED"
    assert last_name_rule.rule_value == "true"
    assert last_name_rule.applies_to == [properties["last_name"].id]

    age_min_rule = rules["age:MIN_VALUE"]
    assert age_min_rule.rule_type == "MIN_VALUE"
    assert age_min_rule.rule_value == "0"
    assert age_min_rule.applies_to == [properties["age"].id]

    age_max_rule = rules["age:MAX_VALUE"]
    assert age_max_rule.rule_type == "MAX_VALUE"
    assert age_max_rule.rule_value == "120"
    assert age_max_rule.applies_to == [properties["age"].id]

    # Provenance: every property, class, and rule gets one ProvenanceEntry
    # from this ingestion.
    for entity in (*properties.values(), person, *rules.values()):
        assert len(entity.provenance) == 1
        prov = provenance_entries[entity.provenance[0]]
        assert prov.had_primary_source == "person"
        assert prov.was_attributed_to == "tester"


def test_print_entities_raw_ids_vs_readable_names(capsys):
    """--verbose prints exactly what's stored (raw UUID references);
    --verbose-readable resolves them to names. Same data, two renderings."""
    from ingest_linkml import _print_entities

    parsed = parse_linkml(FIXTURES / "comprehensive.yml")
    props, classes, vsets, pvs, rules, prov = build_registry_entities(
        parsed, "comprehensive", "tester"
    )
    person = classes["Person"]
    a_prop_id = props["name"].id

    _print_entities(props, classes, vsets, pvs, rules, prov, readable=False)
    raw = capsys.readouterr().out
    _print_entities(props, classes, vsets, pvs, rules, prov, readable=True)
    readable = capsys.readouterr().out

    # The property's own `id:` line prints the id in both modes; the
    # difference is in *reference* fields (a class's `properties:` list etc.),
    # which show the id in raw mode and the name in readable mode. So the id
    # occurs strictly more often in raw, and a resolved name shows up only in
    # readable.
    assert raw.count(a_prop_id) > readable.count(a_prop_id)
    assert "'name'" in readable          # a reference resolved to a name
    assert "'name'" not in raw
