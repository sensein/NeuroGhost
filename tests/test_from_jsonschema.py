"""
Tests for the JSON Schema -> LinkML converter (converters/from_jsonschema.py),
which wraps schema-automator's JsonSchemaImportEngine plus a post-process pass
that recovers the constraint facets the importer drops (pattern/min/max).

The valuable assertion isn't "the importer ran" — it's that a JSON Schema, run
through convert() and then the *real* ingestion path
(parse_linkml -> build_registry_entities), produces the RegistryClasses,
RegistryProperties, and RegistryRules we expect. So these tests go all the way
to build_registry_entities(), same altitude as test_ingest_linkml.py's
build_registry_entities tests.
"""

import json
from pathlib import Path

import yaml

from ingest_linkml import parse_linkml, build_registry_entities
from neuro_ghost.converters.from_jsonschema import convert

FIXTURES = Path(__file__).parent / "fixtures"


def _convert_and_build(data, name: str, tmp_path):
    """JSON Schema (dict or file path) -> convert() -> LinkML .yml ->
    build_registry_entities()."""
    if isinstance(data, Path):
        data = json.loads(data.read_text())
    linkml_dict = convert(data, name)
    yml = tmp_path / f"{name}.yml"
    yml.write_text(yaml.safe_dump(linkml_dict, sort_keys=False))
    parsed = parse_linkml(yml)
    return linkml_dict, build_registry_entities(parsed, name, "tester")


# A property's value type(s) live on its RANGE rules now (one per permitted
# range — a union is several), not on the property node. Read them back as a set.
def _range_vals(rules, prop):
    return {r.rule_value for r in rules.values()
            if r.rule_type == "RANGE" and r.applies_to == [prop.id]}


def test_person_json_schema_maps_to_classes_properties_and_rules(tmp_path):
    """
    person.schema.json exercises the pieces that matter for the registry:
    two objects (root + a $ref'd $def), a $ref-typed property, `required`,
    a `pattern`, numeric `minimum`/`maximum`, and a named enum definition
    (RoleType) referenced by an array property (dandi's controlled-vocab
    idiom). All should survive into RegistryClass / RegistryProperty /
    RegistryRule / RegistryValueSet.
    """
    linkml_dict, built = _convert_and_build(
        FIXTURES / "person.schema.json", "person", tmp_path
    )
    properties, registry_classes, value_sets, permissible_values, rules, provenance = built

    # The two OBJECT defs become classes; the enum def (RoleType) does NOT —
    # it becomes a value set, not an empty class.
    assert set(registry_classes) == {"Person", "Address"}
    assert registry_classes["Person"].description == "An individual human being."
    assert registry_classes["Address"].description == "A postal address."

    # A top-level enum definition -> RegistryValueSet with its permissible
    # values (schema-automator would otherwise drop it as an empty class).
    assert set(value_sets) == {"RoleType"}
    role_values = {
        permissible_values[pv_id].name
        for pv_id in value_sets["RoleType"].permissible_values
    }
    assert role_values == {"author", "editor", "reviewer"}
    # The referencing property's RANGE rule points at that value set, not a class.
    assert _range_vals(rules, properties["roles"]) == {value_sets["RoleType"].id}

    # $ref property -> class-typed RANGE rule (resolved to Address's real id).
    assert _range_vals(rules, properties["address"]) == {registry_classes["Address"].id}

    # age is a real integer with numeric bounds; name has a pattern.
    assert _range_vals(rules, properties["age"]) == {"xsd:integer"}

    # The four constraint facets each became a RegistryRule, applied to the
    # right property. pattern + min/max are the ones schema-automator's
    # importer drops and from_jsonschema.py re-applies.
    by_type = {(r.rule_type, tuple(r.applies_to)): r for r in rules.values()}
    ids = {name: p.id for name, p in properties.items()}

    def rule(rule_type, prop):
        return by_type.get((rule_type, (ids[prop],)))

    assert rule("PATTERN", "name").rule_value == "^[A-Za-z ]+$"
    assert rule("REQUIRED", "last_name").rule_value == "true"
    assert rule("MIN_VALUE", "age").rule_value == "0"
    assert rule("MAX_VALUE", "age").rule_value == "120"

    # Exactly those four CONSTRAINT facets — no phantom rules from
    # unconstrained properties. (RANGE rules are separate; every typed
    # property gets one now, so they're excluded from this facet check.)
    constraint_types = {"PATTERN", "REQUIRED", "MIN_VALUE", "MAX_VALUE"}
    constraint_rules = [r for r in rules.values() if r.rule_type in constraint_types]
    assert {r.rule_type for r in constraint_rules} == constraint_types
    assert len(constraint_rules) == 4


def test_string_length_becomes_a_length_pattern(tmp_path):
    """LinkML has no string min/maxLength facet, so from_jsonschema.py encodes
    JSON Schema minLength/maxLength as a `^[\\s\\S]{lo,hi}$` length pattern —
    but only when the field has no real pattern of its own (a real pattern is
    the more specific constraint and wins)."""
    js = {
        "title": "T", "type": "object",
        "properties": {
            "code":     {"type": "string", "minLength": 1, "maxLength": 8},
            "with_pat": {"type": "string", "minLength": 1, "maxLength": 8,
                         "pattern": "^[A-Z]+$"},
        },
    }
    d = convert(js, "t")
    assert d["slots"]["code"]["pattern"] == r"^[\s\S]{1,8}$"
    # a real pattern is respected — length does NOT clobber it.
    assert d["slots"]["with_pat"]["pattern"] == "^[A-Z]+$"

    # end-to-end: the length pattern becomes a PATTERN RegistryRule.
    yml = tmp_path / "t.yml"
    yml.write_text(yaml.safe_dump(d, sort_keys=False))
    props, classes, vs, pvs, rules, prov = build_registry_entities(
        parse_linkml(yml), "t", "tester"
    )
    code_rules = [r for r in rules.values()
                  if r.applies_to == [props["code"].id] and r.rule_type == "PATTERN"]
    assert code_rules and code_rules[0].rule_value == r"^[\s\S]{1,8}$"


def test_anyof_union_becomes_several_range_rules(tmp_path):
    """An `anyOf` of $refs (dandi's polymorphic idiom, written as an array of
    `anyOf`ed refs) becomes a LinkML union via any_of, and lands on several
    RANGE rules — one per permitted target class id. There is no `range_any_of`
    and no single RANGE rule that's "the" range."""
    js = {
        "title": "Doc", "type": "object",
        "properties": {
            "contributor": {"type": "array", "items": {"anyOf": [
                {"$ref": "#/$defs/Person"}, {"$ref": "#/$defs/Organization"},
            ]}},
            "name": {"type": "string"},   # a plain single-range control
        },
        "$defs": {
            "Person":       {"type": "object", "properties": {"name": {"type": "string"}}},
            "Organization": {"type": "object", "properties": {"legalName": {"type": "string"}}},
        },
    }
    _, built = _convert_and_build(js, "doc", tmp_path)
    properties, registry_classes, value_sets, permissible_values, rules, prov = built

    contributor = properties["contributor"]
    # union: several RANGE rules, one per permitted class id.
    assert _range_vals(rules, contributor) == {
        registry_classes["Person"].id, registry_classes["Organization"].id,
    }
    # a non-union property gets exactly one RANGE rule.
    assert _range_vals(rules, properties["name"]) == {"xsd:string"}


def test_convert_output_is_valid_linkml_shape(tmp_path):
    """convert() returns a dict with the LinkML top-level keys the rest of the
    pipeline (and yaml.dump in schema_submission.yml) expects."""
    data = json.loads((FIXTURES / "person.schema.json").read_text())
    d = convert(data, "person")

    assert d["name"] == "person"
    assert d["id"] == "https://registry.sensein.io/schema/person"
    assert "linkml:types" in d["imports"]
    assert set(d["classes"]) == {"Person", "Address"}


def test_format_maps_to_linkml_type_or_warns(tmp_path, capsys):
    """JSON Schema string `format` maps to a LinkML semantic type where one
    exists (uri/date-time/date/time -> xsd:anyURI/dateTime/date/time). Formats
    with no LinkML type (email, uuid, ...) stay plain string and a warning is
    emitted."""
    js = {
        "title": "T", "type": "object",
        "properties": {
            "homepage": {"type": "string", "format": "uri"},
            "created":  {"type": "string", "format": "date-time"},
            "born":     {"type": "string", "format": "date"},
            "contact":  {"type": "string", "format": "email"},   # no LinkML type
        },
    }
    _, built = _convert_and_build(js, "fmt", tmp_path)
    properties, rules = built[0], built[4]

    assert _range_vals(rules, properties["homepage"]) == {"xsd:anyURI"}
    assert _range_vals(rules, properties["created"]) == {"xsd:dateTime"}
    assert _range_vals(rules, properties["born"]) == {"xsd:date"}
    # unmappable format falls back to string, with a warning naming it.
    assert _range_vals(rules, properties["contact"]) == {"xsd:string"}
    assert "email" in capsys.readouterr().err
