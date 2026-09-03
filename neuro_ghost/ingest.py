"""
ingest.py — format-aware schema ingestion (LinkML or JSON Schema)
=================================================================
The front door for ingesting a single schema, whatever its format:

    python neuro_ghost/ingest.py registry_schemas/bbqs.yml
    python neuro_ghost/ingest.py --dry-run --verbose dandiset.json

WHY THIS EXISTS (vs. ingest_linkml.py)
--------------------------------------
`ingest_linkml.py` is deliberately LinkML-only. This is the format-aware
layer on top: a JSON Schema (.json) is converted to LinkML first (via
converters.from_jsonschema), then handed to the existing LinkML ingester
unchanged — the same convert-then-ingest path the schema-submission
workflow takes, and the same subprocess pattern pipeline.py uses. So
ingest_linkml never sees anything but LinkML.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import yaml

HERE = Path(__file__).parent
DB_PATH = str(HERE.parent / "registry.lbug")


@click.command()
@click.argument("file", metavar="SCHEMA",
                type=click.Path(exists=True, dir_okay=False))
@click.option("--db", default=DB_PATH, show_default=True,
              help="Path to the LadybugDB file.")
@click.option("--dry-run", is_flag=True,
              help="Parse and report without writing to the DB.")
@click.option("--verbose", is_flag=True,
              help="Print every entity that would be created, exactly as "
                   "stored (raw UUID references). Pairs well with --dry-run.")
@click.option("--verbose-readable", is_flag=True,
              help="Like --verbose, but resolve id references to names.")
@click.option("--wipe", is_flag=True,
              help="Remove this source's attestations before re-ingesting.")
@click.option("--registry-version", default="",
              help="Registry semver to stamp on created nodes.")
@click.option("--issue", default="", help="GitHub issue number (for provenance).")
@click.option("--agent", default="anonymous", help="Who submitted this schema.")
@click.option("--format", "fmt", type=click.Choice(["auto", "linkml", "json"]),
              default="auto", show_default=True,
              help="Input format. 'auto' (default) decides by file extension "
                   "(.json = JSON Schema, else LinkML); pass 'linkml'/'json' "
                   "to override for a misnamed file.")
def cli(file: str, db: str, dry_run: bool, verbose: bool, verbose_readable: bool,
        wipe: bool, registry_version: str, issue: str, agent: str, fmt: str) -> None:
    """
    Ingest a LinkML (.yml) or JSON Schema (.json) SCHEMA into the registry.

    JSON Schema is converted to LinkML first, then ingested through the
    normal LinkML path (ingest_linkml.py).
    """
    path = Path(file)
    tmp_yml: str | None = None

    # Format is decided by extension by default; --format overrides it for a
    # file whose extension doesn't match its contents (JSON Schema saved as
    # .yaml, LinkML written as .json, etc.).
    is_json = fmt == "json" or (fmt == "auto" and path.suffix.lower() == ".json")

    if is_json:
        # Convert JSON Schema -> LinkML, write to a temp .yml, ingest that.
        sys.path.insert(0, str(HERE.parent))
        from neuro_ghost.converters.from_jsonschema import convert
        linkml_dict = convert(json.loads(path.read_text()), path.stem)
        tf = tempfile.NamedTemporaryFile(
            "w", suffix=".yml", prefix=f"{path.stem}.", delete=False)
        yaml.safe_dump(linkml_dict, tf, sort_keys=False)
        tf.close()
        tmp_yml = tf.name
        target = tmp_yml
        click.echo(f"Converted {path.name} (JSON Schema) → LinkML "
                   f"({len(linkml_dict.get('classes', {}))} classes, "
                   f"{len(linkml_dict.get('enums', {}))} enums).")
    else:
        target = str(path)

    cmd = [sys.executable, str(HERE / "ingest_linkml.py"),
           "--file", target, "--db", db, "--agent", agent]
    if dry_run:
        cmd.append("--dry-run")
    if verbose:
        cmd.append("--verbose")
    if verbose_readable:
        cmd.append("--verbose-readable")
    if wipe:
        cmd.append("--wipe")
    if registry_version:
        cmd += ["--registry-version", registry_version]
    if issue:
        cmd += ["--issue", issue]

    try:
        result = subprocess.run(cmd)
    finally:
        if tmp_yml:
            os.unlink(tmp_yml)
    sys.exit(result.returncode)


if __name__ == "__main__":
    cli()
