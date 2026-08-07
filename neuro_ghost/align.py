"""
align.py — Minimal placeholder for cross-schema class alignment
==================================================================

NOT the real alignment implementation. NeuroGhost's real alignment work is
meant to come from an external package — Proteus's own proteus-align (see
.github/workflows/track_modules.yml, which tracks upstream commits since the
last time it was synced into this repo). This file used to be a full inline
port of that pipeline (multi-signal scoring: name/token/alias similarity,
unit veto, definition embeddings, structural repair, calibration), but that
meant touching it every time the meta-model changed — aliases, units,
ProvenanceEntry field renames, none of which had anything to do with
alignment logic itself, just with keeping an inlined copy in sync.

This placeholder does the simplest defensible thing instead: exact
class_uri matches only, using just hash_id/class_uri/name — the most
stable fields in the schema, unlikely to be renamed. It exists so
export_json.py's "alignments" export and mcp_server.py's alignment-reading
tools have something real to read, not as a stand-in for real alignment
logic. Do not add more signals here — that work belongs in the external
package; this file should need to change only if the ALIGNED_TO edge shape
itself changes.

ALIGNED_TO edge shape (matches db.py's _migrate_aligned_to()):
  distance, method, skos_relation, score_iri, score_name, score_desc,
  score_slot, registry_version

USAGE
-----
  python align.py                  # exact class_uri matches, all classes
  python align.py --dry-run        # print pairs without writing
"""

from __future__ import annotations

import click

from db import get_connection

DB_PATH = "./registry.lbug"


def load_classes(conn) -> list[dict]:
    """hash_id, class_uri, name for every RegistryClass — nothing else."""
    rows = conn.execute(
        "MATCH (n:RegistryClass) RETURN n.hash_id, n.class_uri, n.name"
    ).get_all()
    return [{"hash_id": h, "class_uri": c or "", "name": n or ""} for h, c, n in rows]


def exact_class_uri_pairs(classes: list[dict]) -> list[tuple[dict, dict]]:
    """Every pair of distinct classes sharing a non-empty class_uri."""
    by_uri: dict[str, list[dict]] = {}
    for c in classes:
        if c["class_uri"]:
            by_uri.setdefault(c["class_uri"], []).append(c)

    pairs = []
    for group in by_uri.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pairs.append((a, b))
    return pairs


def write_alignment(conn, a: dict, b: dict, registry_version: str = "") -> None:
    """Write a skos:exactMatch ALIGNED_TO edge in both directions."""
    for src, dst in ((a, b), (b, a)):
        conn.execute("""
            MATCH (x:RegistryClass {hash_id: $ua})-[r:ALIGNED_TO]->(y:RegistryClass {hash_id: $ub})
            DELETE r
        """, {"ua": src["hash_id"], "ub": dst["hash_id"]})
        conn.execute("""
            MATCH (x:RegistryClass {hash_id: $ua}), (y:RegistryClass {hash_id: $ub})
            CREATE (x)-[:ALIGNED_TO {
                distance: 0.0, method: 'exact_class_uri', skos_relation: 'skos:exactMatch',
                score_iri: 1.0, score_name: 0.0, score_desc: 0.0, score_slot: 0.0,
                registry_version: $rv
            }]->(y)
        """, {"ua": src["hash_id"], "ub": dst["hash_id"], "rv": registry_version})


@click.command()
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--registry-version", default="",
              help="Registry version stamped on ALIGNED_TO edges.")
@click.option("--dry-run", is_flag=True,
              help="Print pairs without writing to graph.")
def cli(db, registry_version, dry_run) -> None:
    """
    Placeholder alignment: exact class_uri matches only.

    Not the real alignment pipeline — see module docstring.
    """
    conn = get_connection(db)
    classes = load_classes(conn)

    if not classes:
        click.echo("No classes found. Run seed.py and ingest_linkml.py first.")
        return

    pairs = exact_class_uri_pairs(classes)

    for a, b in pairs:
        if dry_run:
            click.echo(f"  [exact] {a['name']} <-> {b['name']}  ({a['class_uri']})")
        else:
            write_alignment(conn, a, b, registry_version)

    action = "Would write" if dry_run else "Wrote"
    click.echo(
        f"{action} {len(pairs) * 2} ALIGNED_TO edges "
        f"from {len(pairs)} exact class_uri matches."
    )


if __name__ == "__main__":
    cli()
