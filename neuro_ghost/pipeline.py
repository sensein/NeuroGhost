"""
pipeline.py — Run the full NeuroGhost ingestion pipeline in one command.

Steps
-----
1. (Optional) Delete the database file for a clean rebuild
2. Seed schema.org as the base vocabulary
3. (Optional) Fetch + convert external schemas via converters/run_all.py
4. Ingest every .yml file found in the schemas directory
5. Compute cross-schema alignments
6. Export registry.json + version snapshot

Usage
-----
    # Fresh rebuild — wipe DB, fetch external schemas, ingest everything
    python neuro_ghost/pipeline.py --fresh

    # Re-ingest local schemas only (skip external fetch)
    python neuro_ghost/pipeline.py --fresh --skip-converters

    # Incremental — add one schema to an existing DB
    python neuro_ghost/pipeline.py --skip-converters --schemas schemas/bbqs.yml
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import click

HERE     = Path(__file__).parent
ROOT     = HERE.parent
SCHEMAS  = ROOT / "schemas"
DB_PATH  = str(ROOT / "registry.lbug")


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
              help="Specific .yml files to ingest. Defaults to all files in schemas/.")
@click.option("--bump",             default="minor", show_default=True,
              type=click.Choice(["major", "minor", "patch"]),
              help="Version bump type for the registry export.")
@click.option("--agent",            default="local", show_default=True,
              help="Who is running this pipeline (recorded in provenance).")
@click.option("--issue",            default="",
              help="GitHub issue number to record in provenance (schema submissions).")
def cli(db: str, fresh: bool, skip_converters: bool,
        schemas: tuple, bump: str, agent: str, issue: str) -> None:
    """Run the full NeuroGhost ingestion pipeline."""

    py = sys.executable

    # 1. Fresh wipe
    if fresh:
        db_path = Path(db)
        if db_path.exists():
            db_path.unlink()
            print(f"Deleted {db_path}")

    # 2. Seed schema.org
    _run([py, str(HERE / "seed.py"), "--db", db])

    # 3. External converters
    if not skip_converters:
        _run([py, str(HERE / "converters" / "run_all.py")])

    # 4. Ingest schemas
    targets: list[Path] = (
        [Path(s) for s in schemas]
        if schemas
        else sorted(p for p in SCHEMAS.glob("*.yml")
                    if p.name != "meta_model.yaml")
    )

    if not targets:
        print("No schemas found to ingest.")
        sys.exit(1)

    for schema_file in targets:
        cmd = [py, str(HERE / "ingest_linkml.py"),
               "--file", str(schema_file),
               "--db",   db,
               "--agent", agent]
        if issue:
            cmd += ["--issue", issue]
        _run(cmd)

    # 5. Align
    _run([py, str(HERE / "align.py"), "--db", db])

    # 6. Export
    _run([py, str(HERE / "export_json.py"),
          "--db",    db,
          "--bump",  bump,
          "--agent", agent])

    print("\nPipeline complete.")


if __name__ == "__main__":
    cli()
