"""
Smoke tests for the ingest CLI (neuro_ghost/ingest.py) — the format-aware entry
point that converts JSON Schema to LinkML before handing off to the LinkML
ingester. These are light: they confirm the command wires up and the JSON
path is taken, not the full ingestion (covered by test_from_jsonschema /
test_ingest_*).
"""

from pathlib import Path

from click.testing import CliRunner

from neuro_ghost.ingest import cli

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_json_dry_run(tmp_path):
    """`ingest.py X.json --dry-run` converts the JSON Schema and runs the
    LinkML ingester, exiting 0 without touching the real DB."""
    db = tmp_path / "t.lbug"
    result = CliRunner().invoke(cli, [
        str(FIXTURES / "person.schema.json"),
        "--db", str(db), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    # the JSON->LinkML conversion banner (a click.echo, so it's captured here;
    # the subprocess's own output goes straight to the terminal).
    assert "JSON Schema" in result.output


def test_ingest_format_override(tmp_path):
    """--format json forces the JSON-Schema path even when the extension
    isn't .json (a misnamed file)."""
    misnamed = tmp_path / "schema.txt"
    misnamed.write_text((FIXTURES / "person.schema.json").read_text())
    result = CliRunner().invoke(cli, [
        str(misnamed), "--format", "json",
        "--db", str(tmp_path / "t.lbug"), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "JSON Schema" in result.output


def test_ingest_rejects_missing_file():
    result = CliRunner().invoke(cli, [])
    assert result.exit_code != 0  # SCHEMA argument is required
