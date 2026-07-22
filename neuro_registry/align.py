"""
align.py — Compute and store alignment between schema sources
-------------------------------------------------------------
Compares SchemaClass nodes across different source_labels and writes
ALIGNED_TO edges with a distance score into LadybugDB.

Distance function (current):
  0.0  — IRI match: both classes share the same IRI
           (e.g. bbqs:Publication has class_uri schema:ScholarlyArticle,
           and schema.org seed has iri https://schema.org/ScholarlyArticle)
  1.0  — No IRI match found

Weights are stubbed and ready to extend:
  iri_match    weight=1.0  (only active signal right now)
  name_sim     weight=0.0  (stub — difflib SequenceMatcher)
  desc_sim     weight=0.0  (stub — TF-IDF cosine)
  slot_jaccard weight=0.0  (stub — shared property names)

  distance = 1 - (
      W_IRI   * iri_match    +
      W_NAME  * name_sim     +
      W_DESC  * desc_sim     +
      W_SLOT  * slot_jaccard
  )

The ALIGNED_TO relationship carries:
  distance DOUBLE  — 0.0 identical, 1.0 no relation
  method   STRING  — 'iri' | 'name' | 'desc' | 'composite'

Usage:
    python align.py                    # align all sources against each other
    python align.py --source bbqs      # align bbqs against every other source
    python align.py --dry-run          # print pairs without writing edges
    python align.py --threshold 0.5    # only write edges with distance <= 0.5
"""

from __future__ import annotations
import difflib
from itertools import combinations
from typing import Iterator

import click
import ladybug as lb

# ---------------------------------------------------------------------------
# Distance weights — only IRI active now, rest stubbed at 0
# ---------------------------------------------------------------------------

W_IRI   = 1.0
W_NAME  = 0.0   # stub
W_DESC  = 0.0   # stub
W_SLOT  = 0.0   # stub

DB_PATH = "./registry.lbug"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iri_match(iri_a: str, iri_b: str) -> float:
    """1.0 if IRIs are identical (ignoring trailing slash), else 0.0."""
    if not iri_a or not iri_b:
        return 0.0
    return 1.0 if iri_a.rstrip("/") == iri_b.rstrip("/") else 0.0


def _name_sim(name_a: str, name_b: str) -> float:
    """String similarity between class names. Stub — weight=0."""
    return difflib.SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()


def _desc_sim(desc_a: str, desc_b: str) -> float:
    """TF-IDF cosine similarity between definitions. Stub — weight=0."""
    # TODO: implement with sklearn TfidfVectorizer when scientists confirm
    return 0.0


def _slot_jaccard(slots_a: set[str], slots_b: set[str]) -> float:
    """Jaccard overlap of property IRIs. Stub — weight=0."""
    if not slots_a and not slots_b:
        return 0.0
    intersection = slots_a & slots_b
    union        = slots_a | slots_b
    return len(intersection) / len(union) if union else 0.0


def compute_distance(class_a: dict, class_b: dict) -> tuple[float, str]:
    """
    Returns (distance, method) where distance ∈ [0, 1].
    method indicates which signal drove the result.
    """
    iri_score  = _iri_match(class_a["iri"], class_b["iri"])
    name_score = _name_sim(class_a["name"], class_b["name"])
    desc_score = _desc_sim(class_a["definition"], class_b["definition"])
    slot_score = _slot_jaccard(
        set(class_a.get("slot_iris", [])),
        set(class_b.get("slot_iris", []))
    )

    total_weight = W_IRI + W_NAME + W_DESC + W_SLOT
    if total_weight == 0:
        return 1.0, "none"

    similarity = (
        W_IRI  * iri_score  +
        W_NAME * name_score +
        W_DESC * desc_score +
        W_SLOT * slot_score
    ) / total_weight

    distance = round(1.0 - similarity, 6)

    # Label the dominant method for transparency
    if iri_score == 1.0 and W_IRI > 0:
        method = "iri"
    elif W_NAME > 0 and name_score > 0.8:
        method = "name"
    else:
        method = "composite"

    return distance, method


# ---------------------------------------------------------------------------
# Load classes from DB
# ---------------------------------------------------------------------------

def load_classes(conn: lb.Connection,
                 source_label: str | None = None) -> list[dict]:
    """
    Load SchemaClass nodes from DB with their property IRIs attached.
    Optionally filter by source_label.
    """
    if source_label:
        result = conn.execute("""
            MATCH (n:SchemaClass {source_label: $src})
            RETURN n.uid, n.iri, n.name, n.definition, n.source_label
        """, {"src": source_label})
    else:
        result = conn.execute("""
            MATCH (n:SchemaClass)
            RETURN n.uid, n.iri, n.name, n.definition, n.source_label
        """)

    classes = []
    for row in result.get_all():
        uid, iri, name, definition, src = row

        # Fetch property IRIs for slot overlap (stub)
        prop_result = conn.execute("""
            MATCH (c:SchemaClass {uid: $uid})-[:HAS_PROPERTY]->(p:SchemaProperty)
            RETURN p.iri
        """, {"uid": uid})
        slot_iris = [r[0] for r in prop_result.get_all()]

        classes.append({
            "uid":        uid,
            "iri":        iri or "",
            "name":       name or "",
            "definition": definition or "",
            "source":     src or "",
            "slot_iris":  slot_iris,
        })
    return classes


def pairs_across_sources(
    classes: list[dict],
    source_a: str | None,
) -> Iterator[tuple[dict, dict]]:
    """
    Yield (class_a, class_b) pairs where the two classes come from
    different sources. If source_a is given, one side is always from that source.
    """
    sources = {c["source"] for c in classes}
    if len(sources) < 2:
        return

    if source_a:
        group_a = [c for c in classes if c["source"] == source_a]
        group_b = [c for c in classes if c["source"] != source_a]
        for a in group_a:
            for b in group_b:
                yield a, b
    else:
        by_source = {}
        for c in classes:
            by_source.setdefault(c["source"], []).append(c)
        source_list = list(by_source.keys())
        for s1, s2 in combinations(source_list, 2):
            for a in by_source[s1]:
                for b in by_source[s2]:
                    yield a, b


# ---------------------------------------------------------------------------
# Write alignment edges
# ---------------------------------------------------------------------------

def write_alignment(conn: lb.Connection, uid_a: str, uid_b: str,
                    distance: float, method: str) -> None:
    # Remove existing edge first to avoid duplicates
    conn.execute("""
        MATCH (a:SchemaClass {uid: $ua})-[r:ALIGNED_TO]->(b:SchemaClass {uid: $ub})
        DELETE r
    """, {"ua": uid_a, "ub": uid_b})
    conn.execute("""
        MATCH (a:SchemaClass {uid: $ua}), (b:SchemaClass {uid: $ub})
        CREATE (a)-[:ALIGNED_TO {distance: $d, method: $m}]->(b)
    """, {"ua": uid_a, "ub": uid_b, "d": distance, "m": method})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--source",    default=None,
              help="Align this source against all others. "
                   "Defaults to all source pairs.")
@click.option("--db",        default=DB_PATH, show_default=True,
              help="Path to LadybugDB file.")
@click.option("--threshold", default=1.0, show_default=True, type=float,
              help="Only write ALIGNED_TO edges where distance <= threshold.")
@click.option("--dry-run",   is_flag=True,
              help="Print alignment pairs without writing edges.")
def cli(source: str | None, db: str, threshold: float, dry_run: bool) -> None:
    """Compute alignment (distance) between SchemaClass nodes across sources."""
    conn    = lb.Connection(lb.Database(db))
    classes = load_classes(conn, source_label=None)

    if not classes:
        click.echo("No SchemaClass nodes found in DB. Run seed.py and "
                   "ingest_linkml.py first.")
        return

    sources = {c["source"] for c in classes}
    click.echo(f"Loaded {len(classes)} classes from {len(sources)} sources: "
               f"{', '.join(sorted(sources))}")

    written = 0
    skipped = 0
    exact   = 0

    for a, b in pairs_across_sources(classes, source_a=source):
        distance, method = compute_distance(a, b)

        if distance > threshold:
            skipped += 1
            continue

        if distance == 0.0:
            exact += 1

        if dry_run:
            click.echo(f"  [{method}] {a['source']}:{a['name']} ↔ "
                       f"{b['source']}:{b['name']}  d={distance:.4f}")
        else:
            write_alignment(conn, a["uid"], b["uid"], distance, method)

        written += 1

    action = "Would write" if dry_run else "Wrote"
    click.echo(f"\n{action} {written} ALIGNED_TO edges "
               f"({exact} exact IRI matches, {skipped} above threshold).")

    if not dry_run and written:
        total = conn.execute(
            "MATCH ()-[r:ALIGNED_TO]->() RETURN count(r)"
        ).get_next()[0]
        click.echo(f"Registry total ALIGNED_TO edges: {total}")


if __name__ == "__main__":
    cli()
