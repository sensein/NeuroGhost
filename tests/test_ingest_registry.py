from pathlib import Path

from db import get_connection
from ingest_linkml import insert_schema, parse_linkml

FIXTURES = Path(__file__).parent / "fixtures"


def _conn(tmp_path):
    return get_connection(str(tmp_path / "test.lbug"))


def test_identical_property_from_two_sources_shares_one_hash_id(tmp_path):
    conn = _conn(tmp_path)

    insert_schema(conn, parse_linkml(FIXTURES / "source_a.yml"), "source_a", agent="tester")
    insert_schema(conn, parse_linkml(FIXTURES / "source_b.yml"), "source_b", agent="tester")

    rows = conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.hash_id").get_all()
    assert len(rows) == 1

    sources = conn.execute("""
        MATCH (:RegistryProperty {name: 'age'})-[:HAS_PROVENANCE_P]->(pe:ProvenanceEntry)
        RETURN pe.source
    """).get_all()
    assert {r[0] for r in sources} == {"source_a", "source_b"}


def test_reingesting_same_source_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    parsed = parse_linkml(FIXTURES / "source_a.yml")

    first = insert_schema(conn, parsed, "source_a", agent="tester")
    assert first["classes_new"] == 1
    assert first["properties_new"] == 1
    assert first["provenance_added"] == 2  # one class + one property

    second = insert_schema(conn, parsed, "source_a", agent="tester")
    assert second["classes_new"] == 0
    assert second["properties_new"] == 0
    assert second["provenance_added"] == 0
    assert second.get("schema_unchanged") is True


def test_inherited_slots_and_subclass_edge(tmp_path):
    conn = _conn(tmp_path)
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


def test_required_does_not_affect_property_identity(tmp_path):
    """
    required_a.yml and required_b.yml declare the exact same "age" slot
    (same name/description/range/units) except one marks it `required: true`
    and the other doesn't. RegistryProperty doesn't model required at all
    (deferred to a future Rule — see test_registry_property_does_not_retain_
    usage_constraints in test_ingest_linkml.py), so this must not create a
    second node: same hash_id, one node, provenance from both sources.
    """
    conn = _conn(tmp_path)

    stats_a = insert_schema(conn, parse_linkml(FIXTURES / "required_a.yml"), "required_a", agent="tester")
    stats_b = insert_schema(conn, parse_linkml(FIXTURES / "required_b.yml"), "required_b", agent="tester")

    assert stats_a["properties_new"] == 1
    assert stats_b["properties_new"] == 0        # not a new node — same hash as required_a's
    assert stats_b["properties_existing"] == 1

    rows = conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.hash_id").get_all()
    assert len(rows) == 1                         # no duplicate node

    sources = conn.execute("""
        MATCH (:RegistryProperty {name: 'age'})-[:HAS_PROVENANCE_P]->(pe:ProvenanceEntry)
        RETURN pe.source
    """).get_all()
    assert {r[0] for r in sources} == {"required_a", "required_b"}


def test_content_change_produces_different_hash_id(tmp_path):
    conn = _conn(tmp_path)
    insert_schema(conn, parse_linkml(FIXTURES / "source_a.yml"), "source_a", agent="tester")

    original_hash = conn.execute(
        "MATCH (p:RegistryProperty {name: 'age'}) RETURN p.hash_id"
    ).get_next()[0]

    edited = parse_linkml(FIXTURES / "source_a.yml")
    edited["slots"]["age"]["value_range"] = "float"  # was "integer"
    insert_schema(conn, edited, "source_a_v2", agent="tester")

    hashes = {
        row[0] for row in
        conn.execute("MATCH (p:RegistryProperty {name: 'age'}) RETURN p.hash_id").get_all()
    }
    assert len(hashes) == 2
    assert original_hash in hashes
