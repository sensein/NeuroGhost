"""
pipeline.py — Run the full NeuroGhost ingestion pipeline in one command.

Steps
-----
1. (Optional) Delete the database file for a clean rebuild
2. Seed schema.org as the base vocabulary
3. (Optional) Fetch + convert external schemas via converters/run_all.py
4. Ingest every .yml file found in the registry_schemas directory
5. Compute cross-schema alignments
6. Export registry.json + version snapshot

Usage
-----
    # Fresh rebuild — wipe DB, fetch external schemas, ingest everything
    python neuro_ghost/pipeline.py --fresh

    # Re-ingest local schemas only (skip external fetch)
    python neuro_ghost/pipeline.py --fresh --skip-converters

    # Incremental — add one schema to an existing DB
    python neuro_ghost/pipeline.py --skip-converters --schemas registry_schemas/bbqs.yml
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import click

HERE     = Path(__file__).parent
ROOT     = HERE.parent
SCHEMAS  = ROOT / "registry_schemas"
MAPPINGS = ROOT / "mappings"
DB_PATH  = str(ROOT / "registry.lbug")
# The previous export — read before it is overwritten, so content that's
# already registered keeps its id across --fresh rebuilds.
PREVIOUS = ROOT / "data" / "registry.json"


def _run(cmd: list[str]) -> None:
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\nERROR: command exited with code {result.returncode}")
        sys.exit(result.returncode)


@click.command()
@click.option("--db",               default=DB_PATH, show_default=True,
              help="Path to the LadybugDB file.")
@click.option("--fresh",            is_flag=True,
              help="Delete the DB before starting (clean rebuild).")
@click.option("--skip-converters",  is_flag=True,
              help="Skip fetching external schemas (BIDS, NWB, DANDI, …).")
@click.option("--schemas",          default=None, multiple=True,
              help="Specific .yml files to ingest. Defaults to all files in registry_schemas/.")
@click.option("--bump",             default="minor", show_default=True,
              type=click.Choice(["major", "minor", "patch"]),
              help="Version bump type for the registry export.")
@click.option("--agent",            default="local", show_default=True,
              help="Who is running this pipeline (recorded in provenance).")
@click.option("--issue",            default="",
              help="GitHub issue number to record in provenance (schema submissions).")
@click.option("--carry-ids-by-name", is_flag=True,
              help="One-time: keep ids by (source, name) as well as by hash — "
                   "for the rebuild after a change to how hashes are computed.")
def cli(db: str, fresh: bool, skip_converters: bool,
        schemas: tuple, bump: str, agent: str, issue: str,
        carry_ids_by_name: bool) -> None:
    """Run the full NeuroGhost ingestion pipeline."""

    py = sys.executable

    # 1. Fresh wipe
    if fresh:
        db_path = Path(db)
        if db_path.exists():
            db_path.unlink()
            print(f"Deleted {db_path}")

    # 2. Seed schema.org
    prev_ids = ["--previous-ids", str(PREVIOUS)] if PREVIOUS.exists() else []
    if prev_ids and carry_ids_by_name:
        prev_ids.append("--carry-ids-by-name")
    _run([py, str(HERE / "seed.py"), "--db", db, *prev_ids])

    # 3. External converters
    if not skip_converters:
        _run([py, str(HERE / "converters" / "run_all.py")])

    # 4. Ingest schemas
    targets: list[Path] = (
        [Path(s) for s in schemas]
        if schemas
        else sorted(SCHEMAS.glob("*.yml"))
    )

    if not targets:
        print("No schemas found to ingest.")
        sys.exit(1)

    for schema_file in targets:
        cmd = [py, str(HERE / "ingest_linkml.py"),
               "--file", str(schema_file),
               "--db",   db,
               "--agent", agent, *prev_ids]
        if issue:
            cmd += ["--issue", issue]
        _run(cmd)

    # 5. Align
    _run([py, str(HERE / "align.py"), "--db", db])

    # 6. Mapping files (reviewed cross-schema mappings, mappings/*.sssom.tsv)
    if any(MAPPINGS.glob("*.sssom.tsv")):
        _run([py, str(HERE / "mappings.py"), "load", str(MAPPINGS), "--db", db])

    # 7. Export
    _run([py, str(HERE / "export_json.py"),
          "--db",    db,
          "--bump",  bump,
          "--agent", agent])

    print("\nPipeline complete.")


if __name__ == "__main__":
    cli()
