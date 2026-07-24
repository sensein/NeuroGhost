"""
seed.py — Populate the SenseIn Schema Registry from schema.org

Fetches schema.org's machine-readable JSON-LD and inserts the core type
hierarchy as content-hashed RegistryClass + RegistryProperty nodes, exactly
the way ingest_linkml.py ingests any other schema — schema.org is just
another source, with source="schema.org" on its ProvenanceEntry records.

Seeded types (top-level schema.org hierarchy):
  Thing → CreativeWork, Event, Organization, Person, Place,
           Product, Action, MedicalEntity
  + AudioObject, ImageObject, VideoObject (embedded media)

Each class gets its full set of schema.org properties as RegistryProperty
nodes linked via HAS_PROPERTY.

Usage:
    python seed.py               # inserts into ./registry.lbug
    python seed.py --dry-run     # prints counts, writes nothing
    python seed.py --wipe        # drop + re-seed (use with care)

The script is idempotent: it checks whether Thing already exists before
inserting anything.
"""

from __future__ import annotations
import sys
from pathlib import Path

import click, httpx, rdflib

sys.path.insert(0, str(Path(__file__).parent.parent))
from schema_registry_utils import RegistryClass, RegistryProperty, ProvenanceEntry, compute_hash_id

from db import get_connection, now_iso, write_registry_entities, write_structural_edges

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCHEMA_ORG_JSONLD = (
    "https://schema.org/version/latest/schemaorg-current-https.jsonld"
)

SCHEMA  = rdflib.Namespace("https://schema.org/")
RDFS    = rdflib.RDFS
RDF     = rdflib.RDF

# Curated type list — explicit rather than BFS so we don't pull in
# ComedyEvent, AMRadioChannel, and 900 other irrelevant schema.org types.
#
# Core identity
SEED_ROOTS_CORE = [
    "Thing", "Person", "Organization",
]

# Bio / neuro — MedicalEntity and BioChemEntity subtrees are fully relevant
SEED_ROOTS_BIO = [
    "MedicalEntity",
    "AnatomicalStructure", "BrainStructure", "Nerve", "AnatomicalSystem",
    "MedicalCondition", "InfectiousDisease", "MedicalSignOrSymptom",
    "MedicalStudy", "MedicalObservationalStudy", "MedicalTrial",
    "MedicalProcedure", "DiagnosticProcedure", "TherapeuticProcedure",
    "MedicalTest", "ImagingTest", "BloodTest",
    "MedicalDevice", "Drug", "Substance",
    "BioChemEntity", "Gene", "Protein", "MolecularEntity", "ChemicalSubstance",
]

# Research output
SEED_ROOTS_RESEARCH = [
    "CreativeWork", "Article", "ScholarlyArticle", "Dataset",
    "SoftwareApplication", "SoftwareSourceCode",
]

# Supporting
SEED_ROOTS_SUPPORTING = [
    "Event", "ConferenceEvent", "EducationEvent",
    "Place",
]

SEED_ROOTS = (
    SEED_ROOTS_CORE
    + SEED_ROOTS_BIO
    + SEED_ROOTS_RESEARCH
    + SEED_ROOTS_SUPPORTING
)

# Helpers imported from db.py

# ---------------------------------------------------------------------------
# Fetch + parse schema.org
# ---------------------------------------------------------------------------

def fetch_schema_graph() -> rdflib.Graph:
    print("Fetching schema.org JSON-LD …")
    resp = httpx.get(SCHEMA_ORG_JSONLD, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    g = rdflib.Graph()
    g.parse(data=resp.text, format="json-ld")
    print(f"  Parsed {len(g)} triples.")
    return g


def collect_classes(g: rdflib.Graph) -> dict[str, dict]:
    """
    Return a dict keyed by short name (e.g. "Person") with:
      iri, label, comment, subclass_of (list of short names), props (list)
    Only includes types in SEED_ROOTS — no BFS expansion.
    """
    wanted: set[str] = set(SEED_ROOTS)

    classes: dict[str, dict] = {}
    for name in wanted:
        node    = SCHEMA[name]
        label   = str(next(g.objects(node, RDFS.label),   name))
        comment = str(next(g.objects(node, RDFS.comment), ""))
        parents = [
            str(p).replace("https://schema.org/", "")
            for p in g.objects(node, RDFS.subClassOf)
            if str(p).startswith("https://schema.org/")
        ]
        classes[name] = {
            "iri":         str(node),
            "label":       label,
            "comment":     comment,
            "subclass_of": parents,
            "props":       [],   # filled below
        }

    # Attach properties (schema:domainIncludes links prop → class)
    for prop_node in g.subjects(RDF.type, RDF.Property):
        short_prop = str(prop_node).replace("https://schema.org/", "")
        prop_label = str(next(g.objects(prop_node, RDFS.label),   short_prop))
        prop_comment = str(next(g.objects(prop_node, RDFS.comment), ""))
        ranges = [
            str(r) for r in g.objects(prop_node, SCHEMA.rangeIncludes)
        ]
        for domain in g.objects(prop_node, SCHEMA.domainIncludes):
            short_domain = str(domain).replace("https://schema.org/", "")
            if short_domain in classes:
                classes[short_domain]["props"].append({
                    "name":    short_prop,
                    "iri":     str(prop_node),
                    "label":   prop_label,
                    "comment": prop_comment,
                    "ranges":  ranges,
                })
    return classes

# ---------------------------------------------------------------------------
# Insert into LadybugDB
# ---------------------------------------------------------------------------

def _provenance(agent: str = "system", registry_version: str = "") -> ProvenanceEntry:
    return ProvenanceEntry(
        uid=None, source="schema.org", registry_version=registry_version or None,
        generated_at=now_iso(), attributed_to=agent, activity="seeding",
    )


def build_registry_entities(
    classes: dict[str, dict], registry_version: str = "",
) -> tuple[dict[str, RegistryProperty], dict[str, RegistryClass]]:
    """
    Convert collect_classes()'s output into content-hashed RegistryProperty/
    RegistryClass instances — the same shape ingest_linkml.py produces, so
    schema.org is written by the exact same graph writers as any other source.

    A schema.org class can have multiple rdfs:subClassOf parents; RegistryClass
    only has one `is_a` (LinkML's single-inheritance convention, matching how
    write_structural_edges() only ever creates one SUBCLASS_OF edge per class),
    so only the first resolvable parent is used — any additional parents are
    not represented as edges.
    """
    properties: dict[str, RegistryProperty] = {}
    seen_prop_iris: dict[str, str] = {}   # prop iri -> name, dedupes by IRI

    for info in classes.values():
        for prop in info["props"]:
            if prop["iri"] in seen_prop_iris:
                continue
            seen_prop_iris[prop["iri"]] = prop["name"]
            value_range = prop["ranges"][0] if prop["ranges"] else "xsd:string"
            p = RegistryProperty(
                name=prop["name"],
                description=prop["comment"] or "",
                range=value_range,
                slot_uri=prop["iri"] or None,
                provenance=[_provenance(registry_version=registry_version)],
            )
            p.hash_id = compute_hash_id(p)
            properties[prop["iri"]] = p

    registry_classes: dict[str, RegistryClass] = {}

    def resolve_class(name: str) -> RegistryClass | None:
        if name in registry_classes:
            return registry_classes[name]
        info = classes.get(name)
        if info is None:
            return None  # parent outside SEED_ROOTS — left unresolved

        parent_name = next(
            (p for p in info["subclass_of"] if p in classes), None,
        )
        parent = resolve_class(parent_name) if parent_name else None

        prop_hash_ids = sorted({
            properties[prop["iri"]].hash_id for prop in info["props"]
        })
        rc = RegistryClass(
            name=name,
            description=info["comment"] or "",
            class_uri=info["iri"] or None,
            abstract=False,
            is_a=parent.hash_id if parent else None,
            properties=prop_hash_ids,
            provenance=[_provenance(registry_version=registry_version)],
        )
        rc.hash_id = compute_hash_id(rc)
        registry_classes[name] = rc
        return rc

    for name in classes:
        resolve_class(name)

    return properties, registry_classes


def seed(db_path: str = "./registry.lbug",
         dry_run: bool = False,
         wipe: bool = False,
         registry_version: str = "1.0.0") -> None:

    conn = get_connection(db_path)

    if wipe and not dry_run:
        print("Wiping existing schema.org attestations …")
        conn.execute("""
            MATCH (:RegistryClass)-[:HAS_PROVENANCE]->(pe:ProvenanceEntry {source: 'schema.org'})
            DETACH DELETE pe
        """)
        conn.execute("""
            MATCH (:RegistryProperty)-[:HAS_PROVENANCE_P]->(pe:ProvenanceEntry {source: 'schema.org'})
            DETACH DELETE pe
        """)

    # Idempotency check
    if not dry_run and not wipe:
        r = conn.execute("""
            MATCH (n:RegistryClass {name: 'Thing'})-[:HAS_PROVENANCE]->(:ProvenanceEntry {source: 'schema.org'})
            RETURN n.hash_id LIMIT 1
        """)
        if r.has_next():
            print("schema.org seed already present — skipping. "
                  "Use --wipe to re-seed.")
            return

    g = fetch_schema_graph()
    classes = collect_classes(g)

    print(f"Building {len(classes)} classes …")
    properties, registry_classes = build_registry_entities(classes, registry_version)

    if dry_run:
        print(f"\n[dry-run] Would insert:")
        print(f"  {len(registry_classes)} RegistryClass nodes")
        print(f"  {len(properties)} RegistryProperty nodes (deduplicated)")
        for name, info in sorted(classes.items())[:12]:
            print(f"    {name}: {len(info['props'])} props, "
                  f"parents={info['subclass_of']}")
        print("  … (showing first 12)")
        return

    stats = write_registry_entities(conn, properties, registry_classes)
    rels  = write_structural_edges(conn, registry_classes)

    print(
        f"+{stats['classes_new']} classes, ={stats['classes_existing']} existing | "
        f"+{stats['properties_new']} props, ={stats['properties_existing']} existing | "
        f"+{stats['provenance_added']} provenance entries | +{rels} edges"
    )

    nc = conn.execute("MATCH (n:RegistryClass) RETURN count(n)").get_next()[0]
    np = conn.execute("MATCH (n:RegistryProperty) RETURN count(n)").get_next()[0]
    print(f"\nDone. Registry now has {nc} classes, {np} properties.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--db",      default="./registry.lbug", show_default=True,
              help="Path to LadybugDB file.")
@click.option("--dry-run", is_flag=True,
              help="Print what would be inserted without writing.")
@click.option("--wipe",    is_flag=True,
              help="Delete existing classes/properties before seeding.")
@click.option("--registry-version", default="1.0.0", show_default=True,
              help="Registry semver to stamp on seeded ProvenanceEntry records.")
def cli(db: str, dry_run: bool, wipe: bool, registry_version: str) -> None:
    """Seed the SenseIn Schema Registry from schema.org."""
    seed(db_path=db, dry_run=dry_run, wipe=wipe, registry_version=registry_version)

if __name__ == "__main__":
    cli()
