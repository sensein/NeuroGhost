from conftest import FIXTURES
from ingest_linkml import insert_schema, parse_linkml
from schema_hash import content_hash


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


def test_metadata_splits_source_vs_bundle(conn, tmp_schema):
    """Per-file metadata (title/source_id) is PROPAGATED from the schema onto its
    SchemaSource; sidecar keys route by prefix — `bundle_*` → the SchemaBundle
    (shared), bare keys → the file's SchemaSource (per-file)."""
    schema = _schema(tmp_schema, "myschema", title="My Example Schema",
                     sidecar={"bundle_title": "My Bundle",
                              "bundle_homepage": "https://bundle.example/",
                              "bundle_publisher": "Example Org",
                              "homepage": "https://file.example/"})
    insert_schema(conn, parse_linkml(schema), "myschema", agent="tester")

    # bundle: only the bundle_* keys land here
    b = conn.execute(
        "MATCH (b:SchemaBundle {label: 'myschema'}) "
        "RETURN b.title, b.homepage, b.publisher, b.id").get_next()
    assert b[0] == "My Bundle"                 # bundle_title
    assert b[1] == "https://bundle.example/"   # bundle_homepage
    assert b[2] == "Example Org"               # bundle_publisher

    # source: propagated title/source_id + the bare (per-file) sidecar homepage,
    # and it is part_of that bundle
    s = conn.execute(
        "MATCH (s:SchemaSource {label: 'myschema'}) "
        "RETURN s.title, s.source_id, s.homepage, s.part_of").get_next()
    assert s[0] == "My Example Schema"                 # propagated title:
    assert s[1] == "https://example.org/myschema"      # propagated source_id (schema id:)
    assert s[2] == "https://file.example/"             # bare sidecar homepage → source
    assert s[3] == b[3]                                 # part_of that bundle


def test_sidecar_accepts_both_yaml_and_yml(tmp_path):
    """The sidecar is discovered whether it's named `<stem>_source.yaml` or
    `<stem>_source.yml`."""
    import yaml as _yaml
    from source_metadata import load_source_sidecar
    (tmp_path / "s.yml").write_text("id: x\nname: s\n")
    (tmp_path / "s_source.yml").write_text(_yaml.safe_dump({"homepage": "https://s/"}))
    assert load_source_sidecar(tmp_path / "s.yml") == {"homepage": "https://s/"}


def test_source_provenance_without_sidecar(conn, tmp_schema):
    """No sidecar and no title: → blank bundle title/homepage; the SchemaSource
    still gets source_id from the schema's id: and a synthetic per-file source_iri."""
    schema = _schema(tmp_schema, "bare")
    insert_schema(conn, parse_linkml(schema), "bare", agent="tester")
    b = conn.execute(
        "MATCH (b:SchemaBundle {label: 'bare'}) RETURN b.title, b.homepage").get_next()
    assert b[0] == ""                                   # no bundle_title
    assert b[1] == ""                                   # no sidecar
    s = conn.execute(
        "MATCH (s:SchemaSource {label: 'bare'}) RETURN s.source_id, s.source_iri").get_next()
    assert s[0] == "https://example.org/bare"           # source_id from schema id:
    assert s[1].startswith("https://registry.sensein.io/source/")  # synthetic per-file iri


def test_export_snapshot_includes_bundle_and_source_metadata(conn, tmp_schema):
    """export_snapshot() surfaces bundle_* metadata in bundles[] and per-file
    provenance in sources[] (each part_of its bundle) — also a regression test
    that export runs at all."""
    from export_json import export_snapshot
    schema = _schema(tmp_schema, "es", title="ES Schema",
                     sidecar={"bundle_title": "ES Bundle",
                              "bundle_homepage": "https://es.example/"})
    insert_schema(conn, parse_linkml(schema), "es", agent="tester")
    snap = export_snapshot(conn, "1.0.0")
    bnd = next(b for b in snap["bundles"] if b["label"] == "es")
    assert bnd["title"] == "ES Bundle"                  # bundle_title
    assert bnd["homepage"] == "https://es.example/"     # bundle_homepage
    assert bnd["parts"] == ["es"]
    src = next(s for s in snap["sources"] if s["label"] == "es")
    assert src["bundle"] == "es"
    assert src["title"] == "ES Schema"                  # propagated per-file title
    assert src["source_id"] == "https://example.org/es"  # per-file source_id


def test_schema_source_records_and_exports_content_hash(conn):
    """The file-level content_hash is stored on SchemaSource and surfaced in the
    export so the UI can pre-check a dropped/pasted file against known sources."""
    from export_json import export_snapshot

    insert_schema(conn, parse_linkml(FIXTURES / "source_a.yml"), "source_a", agent="tester")

    expected = content_hash((FIXTURES / "source_a.yml").read_text())
    stored = conn.execute(
        "MATCH (s:SchemaSource {label: 'source_a'}) RETURN s.content_hash"
    ).get_next()[0]
    assert stored == expected

    snap = export_snapshot(conn, "1.0.0")
    src = next(s for s in snap["sources"] if s["label"] == "source_a")
    assert src["content_hash"] == expected


def test_identical_file_under_a_new_label_is_rejected(conn):
    """Re-adding the exact same schema file under a DIFFERENT source label is
    rejected up front — 'this schema is already in the registry' — creating no
    second SchemaSource and no extra provenance. (Re-ingesting the SAME label is
    an update, covered by test_reingesting_same_source_is_idempotent.)"""
    parsed = parse_linkml(FIXTURES / "source_a.yml")

    first = insert_schema(conn, parsed, "source_a", agent="tester")
    assert first["classes_new"] == 1
    assert not first.get("skipped")

    second = insert_schema(conn, parsed, "source_a_copy", agent="tester")
    assert second.get("skipped") is True
    assert second["duplicate_of"] == "source_a"
    assert second["classes_new"] == 0
    assert second["provenance_added"] == 0

    # No SchemaSource was created for the rejected label.
    labels = {
        r[0] for r in
        conn.execute("MATCH (s:SchemaSource) RETURN s.label").get_all()
    }
    assert labels == {"source_a"}


def test_repeated_class_in_a_different_schema_dedups_but_is_not_rejected(conn):
    """A schema that REUSES a class also defined in another schema — but is not
    a byte-identical file — must NOT be caught by the file-level content_hash
    guard. The shared class dedups to one sha256_hash (existing behaviour), the
    new schema's own class is still added, and both sources are ingested.

    This is the counterpart to test_identical_file_under_a_new_label_is_rejected:
    the file guard rejects only whole-file duplicates, never a partial overlap.
    """
    a = insert_schema(conn, parse_linkml(FIXTURES / "shared_class_a.yml"), "shared_a", agent="tester")
    b = insert_schema(conn, parse_linkml(FIXTURES / "shared_class_b.yml"), "shared_b", agent="tester")

    assert not b.get("skipped")          # different file → not rejected
    assert a["classes_new"] == 2         # Sample + OnlyInA
    assert b["classes_new"] == 1         # OnlyInB only — Sample deduped
    assert b["classes_existing"] == 1    # Sample already present

    # Sample is one shared node; OnlyInA and OnlyInB both exist; both sources kept.
    sample = conn.execute("MATCH (c:RegistryClass {name: 'Sample'}) RETURN c.sha256_hash").get_all()
    assert len(sample) == 1
    names = {r[0] for r in conn.execute("MATCH (c:RegistryClass) RETURN c.name").get_all()}
    assert {"Sample", "OnlyInA", "OnlyInB"} <= names
    src_labels = {r[0] for r in conn.execute("MATCH (s:SchemaSource) RETURN s.label").get_all()}
    assert src_labels == {"shared_a", "shared_b"}


def test_multiple_files_sharing_a_bundle_name_join_one_bundle(conn, tmp_schema):
    """Two files that declare the same `bundle_label` (via their sidecar) join a
    single SchemaBundle as separate parts — the multi-file case (DANDI =
    dandiset + asset). The bundle name is the predictable, submitter-chosen key:
    the first file creates it, the second resolves and joins it. Identical
    classes across the files still dedup."""
    import yaml as _yaml

    def make(name, classes):
        path = tmp_schema(name, {
            "id": f"https://example.org/{name}", "name": name, "title": "DANDI",
            "prefixes": {"linkml": "https://w3id.org/linkml/"},
            "default_range": "string", "imports": ["linkml:types"],
            "classes": classes,
        })
        (path.parent / f"{name}_source.yaml").write_text(_yaml.safe_dump({"bundle_label": "dandi"}))
        return path

    contact = {"ContactPoint": {"attributes": {"email": {"range": "string"}}}}
    p1 = make("dandiset", {"Dandiset": {"attributes": {"identifier": {"range": "string"}}}, **contact})
    p2 = make("asset", {"Asset": {"attributes": {"path": {"range": "string"}}}, **contact})
    insert_schema(conn, parse_linkml(p1), "dandiset", agent="t")
    insert_schema(conn, parse_linkml(p2), "asset", agent="t")

    # exactly one bundle, named "dandi" (the shared bundle_label)
    bundles = conn.execute("MATCH (b:SchemaBundle) RETURN b.id, b.label").get_all()
    assert len(bundles) == 1
    bid, blabel = bundles[0]
    assert blabel == "dandi"

    # both files are their own SchemaSource, both part_of the one bundle
    parts = {r[0] for r in conn.execute("MATCH (s:SchemaSource) RETURN s.label").get_all()}
    assert parts == {"dandiset", "asset"}
    part_ofs = {r[0] for r in conn.execute("MATCH (s:SchemaSource) RETURN s.part_of").get_all()}
    assert part_ofs == {bid}

    # the identical ContactPoint class collapses to one node across the two files
    cp = conn.execute("MATCH (c:RegistryClass {name: 'ContactPoint'}) RETURN count(c)").get_next()[0]
    assert cp == 1
