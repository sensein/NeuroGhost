from conftest import FIXTURES
from ingest_linkml import insert_schema, parse_linkml


def test_identical_property_from_two_sources_collapses_to_one_entity(conn):
    """
    Identity is content-derived only — no source-anchoring field is part of
    the sha256_hash — so identical content ingested from two different schemas
    collapses to one RegistryProperty node (dedup reuses its id), which accumulates one
    ProvenanceEntry per attesting source. This is how identity stays
    separate from provenance: nothing about the entity's sha256_hash depends on
    where it came from, and the shared id follows.
    """
    insert_schema(conn, parse_linkml(FIXTURES / "source_a.yml"), "source_a", agent="tester")
    insert_schema(conn, parse_linkml(FIXTURES / "source_b.yml"), "source_b", agent="tester")

    rows = conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.sha256_hash").get_all()
    shas = {r[0] for r in rows}
    assert len(shas) == 1

    labels = conn.execute("""
        MATCH (p:RegistryProperty {name: 'age'})-[:HAS_PROVENANCE_P]->(:ProvenanceEntry)-[:HAD_PRIMARY_SOURCE]->(ss:SchemaSource)
        RETURN ss.label
    """).get_all()
    assert {r[0] for r in labels} == {"source_a", "source_b"}


def test_aliases_round_trip_through_the_graph(conn):
    """
    aliases is a plain multivalued string field (not a UUID-reference list
    like properties), so it's written to a native list column
    (STRING[] — see db.py's _build_registry_ddl()) rather than an edge, and
    NOT JSON-encoded into a STRING column: a bound string that looks like a
    Cypher list literal gets silently reparsed and corrupted by the DB
    engine. Confirm it survives the write/read round trip through the real
    graph, not just in-memory.
    """
    insert_schema(conn, parse_linkml(FIXTURES / "comprehensive.yml"), "comprehensive", agent="tester")

    prop_rows = conn.execute(
        "MATCH (p:RegistryProperty {name: 'orcid'}) RETURN p.aliases"
    ).get_all()
    assert prop_rows[0][0] == ["ORCID iD"]

    class_rows = conn.execute(
        "MATCH (c:RegistryClass {name: 'Person'}) RETURN c.aliases"
    ).get_all()
    assert class_rows[0][0] == ["Investigator"]


def test_reingesting_same_source_is_idempotent(conn):
    parsed = parse_linkml(FIXTURES / "source_a.yml")

    first = insert_schema(conn, parsed, "source_a", agent="tester")
    assert first["classes_new"] == 1
    assert first["properties_new"] == 1
    assert first["provenance_added"] == 3  # one class + one property + its RANGE rule

    second = insert_schema(conn, parsed, "source_a", agent="tester")
    assert second["classes_new"] == 0
    assert second["properties_new"] == 0
    assert second["provenance_added"] == 0
    assert second.get("schema_unchanged") is True


def test_inherited_slots_and_subclass_edge(conn):
    insert_schema(conn, parse_linkml(FIXTURES / "hierarchy.yml"), "hierarchy", agent="tester")

    props = conn.execute("""
        MATCH (c:RegistryClass {name: 'Sensor'})-[:HAS_PROPERTY]->(p:RegistryProperty)
        RETURN p.name
    """).get_all()
    assert {r[0] for r in props} == {"manufacturer", "sampling_rate"}

    parent = conn.execute("""
        MATCH (c:RegistryClass {name: 'Sensor'})-[:SUBCLASS_OF]->(p:RegistryClass)
        RETURN p.name
    """).get_all()
    assert parent == [["Device"]]


def test_required_does_not_affect_property_identity(conn):
    """
    required_a.yml and required_b.yml declare the exact same "age" slot
    (same name/description/range/units) except one marks it `required: true`
    and the other doesn't. RegistryProperty doesn't model required at all
    (deferred to a future RegistryRule — see test_registry_property_does_not_retain_
    usage_constraints in test_ingest_linkml.py), so within a single source
    this must not create a second node: same sha256_hash, one node.

    Both YAMLs are ingested under the same source label, isolating the
    `required` flag as the only differing input, which is what the test
    asserts is irrelevant to identity.
    """
    stats_a = insert_schema(conn, parse_linkml(FIXTURES / "required_a.yml"), "required", agent="tester")
    stats_b = insert_schema(conn, parse_linkml(FIXTURES / "required_b.yml"), "required", agent="tester")

    assert stats_a["properties_new"] == 1
    assert stats_b["properties_new"] == 0        # not a new node — same hash within one source
    assert stats_b["properties_existing"] == 1

    rows = conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.sha256_hash").get_all()
    assert len(rows) == 1                         # no duplicate node


def test_content_change_produces_different_entity(conn):
    """
    Same source, edited content → new hash. Both ingests use the same
    source label ("source_a"), isolating the description edit as the sole
    driver of the hash change.

    A range edit is deliberately NOT tested here — range is not part of
    RegistryProperty identity at all (it's not a field on the property; it
    lives on a RANGE RegistryRule, which carries the range in its own
    HashSubset). So a range change edits the rule, not the property.
    """
    insert_schema(conn, parse_linkml(FIXTURES / "source_a.yml"), "source_a", agent="tester")

    original_sha = conn.execute(
        "MATCH (p:RegistryProperty {name: 'age'}) RETURN p.sha256_hash"
    ).get_next()[0]

    edited = parse_linkml(FIXTURES / "source_a.yml")
    edited["slots"]["age"]["definition"] = "Age of the subject in years"  # was "Age of the subject"
    insert_schema(conn, edited, "source_a", agent="tester")

    shas = {
        row[0] for row in
        conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.sha256_hash").get_all()
    }
    assert len(shas) == 2
    assert original_sha in shas


def test_bican_prov_ingests_expected_classes_and_properties(conn):
    """
    bican_prov.yaml (github.com/brain-bican/models) is a small, real-world
    schema: two classes, three properties, and — notably — a slot whose
    range is another class in the same schema (used: range ProvEntity).
    Confirms each property's range is written as a RANGE RegistryRule whose
    rule_value is the real RegistryClass id (resolved from the synthetic
    make_iri() placeholder), reachable in the graph via APPLIES_TO_P.

    """
    insert_schema(conn, parse_linkml(FIXTURES / "bican_prov.yaml"), "bican_prov", agent="tester")

    classes = {
        row[0]: row[1] for row in
        conn.execute("MATCH (c:RegistryClass) RETURN c.name, c.id").get_all()
    }
    assert set(classes) == {"ProvActivity", "ProvEntity"}

    # Range lives on a RANGE rule now: rule -[:APPLIES_TO_P]-> property, with
    # rule_value the target class id.
    rng_rows = conn.execute("""
        MATCH (rr:RegistryRule)-[:APPLIES_TO_P]->(p:RegistryProperty)
        WHERE rr.rule_type = 'RANGE'
        RETURN p.name, rr.rule_value
    """).get_all()
    range_by_name = {name: rng for name, rng in rng_rows}
    assert set(range_by_name) == {"used", "was_derived_from", "was_generated_by"}

    # rule_value must be the real RegistryClass id, not the synthetic
    # make_iri("ProvEntity")-style placeholder _slot_to_dict() starts with.
    assert range_by_name["used"] == classes["ProvEntity"]
    assert range_by_name["was_derived_from"] == classes["ProvEntity"]
    assert range_by_name["was_generated_by"] == classes["ProvActivity"]

    has_property = conn.execute("""
        MATCH (c:RegistryClass)-[:HAS_PROPERTY]->(p:RegistryProperty)
        RETURN c.name, p.name
    """).get_all()
    assert set(map(tuple, has_property)) == {
        ("ProvActivity", "used"),
        ("ProvEntity", "was_derived_from"),
        ("ProvEntity", "was_generated_by"),
    }


def _schema(tmp_schema, name, *, title=None, sidecar=None):
    """A minimal LinkML schema written via the conftest `tmp_schema` factory
    (id: + optional title:), plus an optional `<name>_source.yaml` sidecar next
    to it. Returns the schema path."""
    import yaml
    body = {
        "id": f"https://example.org/{name}", "name": name,
        "prefixes": {"linkml": "https://w3id.org/linkml/"},
        "default_range": "string", "imports": ["linkml:types"],
        "classes": {"Thing": {"attributes": {"x": {"range": "string"}}}},
    }
    if title:
        body["title"] = title
    path = tmp_schema(name, body)
    if sidecar is not None:
        (path.parent / f"{name}_source.yaml").write_text(yaml.safe_dump(sidecar))
    return path


def test_schema_source_propagates_and_overlays_metadata(conn, tmp_schema):
    """title/source_iri are PROPAGATED from the schema's own title:/id:; the
    optional <stem>_source.yaml sidecar supplies homepage/publisher/contact."""
    schema = _schema(tmp_schema, "myschema", title="My Example Schema",
                     sidecar={"homepage": "https://example.org/",
                              "publisher": "Example Org"})
    insert_schema(conn, parse_linkml(schema), "myschema", agent="tester")
    row = conn.execute(
        "MATCH (s:SchemaSource {label: 'myschema'}) "
        "RETURN s.title, s.source_id, s.homepage, s.publisher"
    ).get_next()
    assert row[0] == "My Example Schema"             # propagated title
    assert row[1] == "https://example.org/myschema"  # propagated source_id (schema id:)
    assert row[2] == "https://example.org/"          # sidecar homepage
    assert row[3] == "Example Org"                    # sidecar publisher


def test_sidecar_accepts_both_yaml_and_yml(tmp_path):
    """The sidecar is discovered whether it's named `<stem>_source.yaml` or
    `<stem>_source.yml`."""
    import yaml as _yaml
    from source_metadata import load_source_sidecar
    (tmp_path / "s.yml").write_text("id: x\nname: s\n")
    (tmp_path / "s_source.yml").write_text(_yaml.safe_dump({"homepage": "https://s/"}))
    assert load_source_sidecar(tmp_path / "s.yml") == {"homepage": "https://s/"}


def test_schema_source_without_sidecar_is_blank(conn, tmp_schema):
    """No sidecar and no title: → blank supplemental fields; source_iri still
    propagates from the schema's id:."""
    schema = _schema(tmp_schema, "bare")
    insert_schema(conn, parse_linkml(schema), "bare", agent="tester")
    row = conn.execute(
        "MATCH (s:SchemaSource {label: 'bare'}) RETURN s.title, s.homepage, s.source_id, s.source_iri"
    ).get_next()
    assert row[0] == ""                                 # no title:
    assert row[1] == ""                                 # no sidecar
    assert row[2] == "https://example.org/bare"         # source_id from schema id:
    assert row[3].startswith("https://registry.sensein.io/source/")  # synthetic source_iri


def test_export_snapshot_includes_source_metadata(conn, tmp_schema):
    """export_snapshot() surfaces the metadata in sources[] — and this doubles
    as a regression test that export runs at all (it previously crashed in
    _attesting_sources on an undefined name)."""
    from export_json import export_snapshot
    schema = _schema(tmp_schema, "es", title="ES Schema",
                     sidecar={"homepage": "https://es.example/"})
    insert_schema(conn, parse_linkml(schema), "es", agent="tester")
    snap = export_snapshot(conn, "1.0.0")
    src = next(s for s in snap["sources"] if s["label"] == "es")
    assert src["title"] == "ES Schema"
    assert src["homepage"] == "https://es.example/"
    assert src["source_id"] == "https://example.org/es"
