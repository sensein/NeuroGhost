"""
mappings.py — Mapping files (mappings/*.sssom.tsv) -> Mapping records
=====================================================================
A mapping file is a reviewed, hand-editable record of cross-schema
correspondences ("aind:Subject.sex closeMatch bids:Columns.sex"), produced by
any method — embeddings in CI, a person's own LLM via the propose-mappings
skill, Proteus later — and always merged through a PR. The rebuild loads every
file into Mapping + MappingProvenanceEntry nodes; nothing here computes
mappings.

Format: SSSOM-style TSV with a `# key: value` metadata header whose values
are defaults for every row (a row's own column wins):

    # mapping_set_id: 2026-10-18_embeddings_aind__bids
    # mapping_date: 2026-10-18
    # mapping_tool: embeddings/all-MiniLM-L6-v2
    # mapping_justification: semapv:SemanticSimilarityThresholdMatching
    # author_id: github-actions
    subject_id  predicate_id  object_id  confidence  review_status  author_id  reviewer_id  review_date  comment

  * subject_id / object_id: `source:Class` or `source:Class.prop` — the
    source label, then a class name, then optionally one of that class's
    property names. Not UUIDs: files are read and edited by hand.
  * predicate_id: skos:exactMatch | closeMatch | broadMatch | narrowMatch |
    relatedMatch, or owl:equivalentClass.
  * review_status: PROPOSED | ACCEPTED | REJECTED | SUPERSEDED.
  * reviewer_id (+ review_date): who accepted/rejected it — becomes a second
    provenance entry, so "proposed by X, reviewed by Y" is kept.
  * comment: free text (e.g. an LLM's rationale); kept in the file only.

Mapping and provenance ids are uuid5s of their content (mapping set,
subject, predicate, object), so they are the same on every rebuild without
any id memory, and timestamps come from the file, not from the rebuild.

Usage:
    python neuro_ghost/mappings.py validate mappings/ --registry data/registry.json
    python neuro_ghost/mappings.py load mappings/ --db registry.lbug
    python neuro_ghost/mappings.py check-reviewers mappings/x.sssom.tsv --author djarecka --base base/
"""
from __future__ import annotations

import csv
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import click

PREDICATES = {
    "skos:exactMatch":     "EXACT_MATCH",
    "skos:closeMatch":     "CLOSE_MATCH",
    "skos:broadMatch":     "BROAD_MATCH",
    "skos:narrowMatch":    "NARROW_MATCH",
    "skos:relatedMatch":   "RELATED_MATCH",
    "owl:equivalentClass": "EQUIVALENT_CLASS",
}
REVIEW_STATUSES = {"PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED"}
REQUIRED_COLUMNS = ("subject_id", "predicate_id", "object_id")
REQUIRED_META = ("mapping_set_id", "mapping_date")

# Namespace for the content-derived Mapping / provenance ids.
_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://registry.sensein.io/mapping")


@dataclass
class Ref:
    """A parsed `source:Class[.prop]` reference."""
    source: str
    cls: str
    prop: str | None = None

    @classmethod
    def parse(cls, text: str) -> "Ref":
        source, sep, rest = text.partition(":")
        if not sep or not source or not rest:
            raise ValueError(f"not a source:Class[.prop] reference: {text!r}")
        name, _, prop = rest.partition(".")
        if not name:
            raise ValueError(f"no class name in {text!r}")
        return cls(source, name, prop or None)

    def __str__(self) -> str:
        return f"{self.source}:{self.cls}" + (f".{self.prop}" if self.prop else "")


@dataclass
class MappingRow:
    subject: Ref
    predicate: str           # CURIE as written
    object: Ref
    review_status: str
    confidence: float | None
    mapping_set_id: str
    mapping_date: str
    mapping_tool: str
    mapping_justification: str
    author_id: str
    reviewer_id: str = ""
    review_date: str = ""
    comment: str = ""
    file: str = ""
    line: int = 0

    @property
    def key(self) -> str:
        return f"{self.mapping_set_id}|{self.subject}|{self.predicate}|{self.object}"

    @property
    def mapping_id(self) -> str:
        return str(uuid.uuid5(_NS, self.key))


@dataclass
class MappingFile:
    path: Path
    meta: dict[str, str] = field(default_factory=dict)
    rows: list[MappingRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def read_mapping_file(path: Path) -> MappingFile:
    """Parse one mapping file. Problems are collected in `.errors` (with
    line numbers) rather than raised, so a validator can report them all."""
    mf = MappingFile(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            body_start = i
            break
        key, sep, value = line[1:].partition(":")
        if sep:
            mf.meta[key.strip()] = value.strip()
    else:
        body_start = len(lines)

    for key in REQUIRED_META:
        if not mf.meta.get(key):
            mf.errors.append(f"{path}: header is missing `# {key}: ...`")

    reader = csv.DictReader(lines[body_start:], delimiter="\t")
    missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        mf.errors.append(f"{path}: missing column(s) {missing}")
        return mf

    for offset, rec in enumerate(reader, start=2):
        lineno = body_start + offset
        where = f"{path}:{lineno}"

        def val(col: str) -> str:
            return (rec.get(col) or "").strip() or mf.meta.get(col, "")

        try:
            subject, obj = Ref.parse(val("subject_id")), Ref.parse(val("object_id"))
        except ValueError as e:
            mf.errors.append(f"{where}: {e}")
            continue
        predicate = val("predicate_id")
        if predicate not in PREDICATES:
            mf.errors.append(f"{where}: predicate {predicate!r} is not one of {sorted(PREDICATES)}")
            continue
        status = val("review_status") or "PROPOSED"
        if status not in REVIEW_STATUSES:
            mf.errors.append(f"{where}: review_status {status!r} is not one of {sorted(REVIEW_STATUSES)}")
            continue
        confidence = None
        if val("confidence"):
            try:
                confidence = float(val("confidence"))
            except ValueError:
                mf.errors.append(f"{where}: confidence {val('confidence')!r} is not a number")
                continue
        if not val("author_id"):
            mf.errors.append(f"{where}: no author_id (row or header)")
            continue
        if status in ("ACCEPTED", "REJECTED") and not val("reviewer_id"):
            mf.errors.append(f"{where}: {status} needs a reviewer_id")
            continue
        mf.rows.append(MappingRow(
            subject=subject, predicate=predicate, object=obj, review_status=status,
            confidence=confidence,
            mapping_set_id=mf.meta.get("mapping_set_id", ""),
            mapping_date=val("mapping_date"),
            mapping_tool=val("mapping_tool"),
            mapping_justification=val("mapping_justification"),
            author_id=val("author_id"), reviewer_id=val("reviewer_id"),
            review_date=val("review_date"), comment=val("comment"),
            file=str(path), line=lineno,
        ))
    return mf


def read_mapping_files(paths: list[Path]) -> list[MappingFile]:
    files: list[Path] = []
    for p in paths:
        files += sorted(p.glob("*.sssom.tsv")) if p.is_dir() else [p]
    return [read_mapping_file(f) for f in files]


# ---------------------------------------------------------------------------
# Resolving references
# ---------------------------------------------------------------------------

class RegistryIndex:
    """`source:Class[.prop]` -> entity id, from a registry.json export."""

    def __init__(self, registry: dict):
        self.ids: dict[str, str] = {}
        for c in registry.get("classes", []):
            for source in c.get("sources", []):
                self.ids[f"{source}:{c['name']}"] = c["id"]
                for p in c.get("properties", []):
                    self.ids[f"{source}:{c['name']}.{p['name']}"] = p["id"]

    def resolve(self, ref: Ref) -> str | None:
        return self.ids.get(str(ref))


def resolve_in_graph(conn, ref: Ref) -> tuple[str, str] | None:
    """(node label, id) of a reference in the graph, or None."""
    cls_match = """
        MATCH (c:RegistryClass {name: $cls})-[:HAS_PROVENANCE]->(:ProvenanceEntry)
              -[:HAD_PRIMARY_SOURCE]->(:SchemaSource {label: $src})
    """
    params = {"cls": ref.cls, "src": ref.source}
    if ref.prop is None:
        r = conn.execute(cls_match + " RETURN DISTINCT c.id", params)
        return ("RegistryClass", r.get_next()[0]) if r.has_next() else None
    r = conn.execute(
        cls_match + " MATCH (c)-[:HAS_PROPERTY]->(p:RegistryProperty {name: $prop})"
                    " RETURN DISTINCT p.id",
        {**params, "prop": ref.prop})
    return ("RegistryProperty", r.get_next()[0]) if r.has_next() else None


# ---------------------------------------------------------------------------
# Loading into the graph
# ---------------------------------------------------------------------------

def _timestamp(date: str) -> str:
    """A file date ("2026-10-18" or a full ISO timestamp) as ISO 8601."""
    return date if "T" in date else f"{date}T00:00:00+00:00"


def load_rows(conn, rows: list[MappingRow], registry_version: str = "") -> dict:
    """Write each row as a Mapping (+ its provenance) attached to its subject.
    Rows whose subject or object doesn't resolve are skipped and reported."""
    stats = {"loaded": 0, "unresolved": []}
    for row in rows:
        subject = resolve_in_graph(conn, row.subject)
        target = resolve_in_graph(conn, row.object)
        if not subject or not target:
            stats["unresolved"].append(f"{row.file}:{row.line}: "
                                       f"{row.subject if not subject else row.object}")
            continue
        mid = row.mapping_id
        if conn.execute("MATCH (m:Mapping {id: $id}) RETURN m.id", {"id": mid}).has_next():
            continue  # the same row in two files of one mapping set
        conn.execute("""
            CREATE (:Mapping {id: $id, mapping_type: $type, target: $target,
                              confidence: $confidence, review_status: $status,
                              mapping_set_id: $set})
        """, {"id": mid, "type": PREDICATES[row.predicate], "target": target[1],
              "confidence": row.confidence, "status": row.review_status,
              "set": row.mapping_set_id})
        rel = "HAS_SKOS_MAPPING" if subject[0] == "RegistryClass" else "HAS_SKOS_MAPPING_P"
        conn.execute(f"""
            MATCH (s:{subject[0]} {{id: $sid}}), (m:Mapping {{id: $mid}})
            CREATE (s)-[:{rel}]->(m)
        """, {"sid": subject[1], "mid": mid})

        entries = [("proposal", row.author_id, row.mapping_date, "mapping")]
        if row.reviewer_id:
            entries.append(("review", row.reviewer_id, row.review_date or row.mapping_date, "review"))
        for kind, agent, date, activity in entries:
            conn.execute("""
                CREATE (:MappingProvenanceEntry {
                    id: $id, attests_to: $mid, registry_version: $rv,
                    generated_at_time: $at, was_attributed_to: $agent,
                    was_generated_by: $activity, was_derived_from: [],
                    mapping_justification: $just, match_string: [],
                    mapping_tool: $tool})
            """, {"id": str(uuid.uuid5(_NS, f"{row.key}|{kind}")), "mid": mid,
                  "rv": registry_version, "at": _timestamp(date), "agent": agent,
                  "activity": activity,
                  "just": row.mapping_justification if kind == "proposal" else "",
                  "tool": row.mapping_tool if kind == "proposal" else ""})
        stats["loaded"] += 1
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Validate or load mapping files."""


@cli.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--registry", default="data/registry.json", show_default=True,
              type=click.Path(exists=True, path_type=Path),
              help="registry.json export to resolve references against.")
def validate(paths: tuple[Path, ...], registry: Path) -> None:
    """Check mapping files: format, values, and that every reference resolves."""
    index = RegistryIndex(json.loads(registry.read_text()))
    errors: list[str] = []
    n_rows = 0
    for mf in read_mapping_files(list(paths)):
        errors += mf.errors
        n_rows += len(mf.rows)
        for row in mf.rows:
            for ref in (row.subject, row.object):
                if index.resolve(ref) is None:
                    errors.append(f"{row.file}:{row.line}: {ref} is not in {registry}")
    for e in errors:
        click.echo(f"ERROR {e}", err=True)
    click.echo(f"{n_rows} mapping(s) checked, {len(errors)} problem(s).")
    sys.exit(1 if errors else 0)


def unattributed_reviews(rows: list[MappingRow], base_rows: list[MappingRow],
                         authors: set[str]) -> list[str]:
    """Rows a PR newly accepts or rejects (absent from `base_rows`, or with a
    different status or reviewer there) whose reviewer_id isn't one of the
    PR's `authors` (its opener and the authors of its commits — GitHub
    vouches for both). That's what makes "who approved it" trustworthy;
    reviews made in earlier PRs are left alone."""
    before = {(r.mapping_set_id, str(r.subject), r.predicate, str(r.object)):
              (r.review_status, r.reviewer_id) for r in base_rows}
    problems = []
    for r in rows:
        if r.review_status not in ("ACCEPTED", "REJECTED"):
            continue
        key = (r.mapping_set_id, str(r.subject), r.predicate, str(r.object))
        if before.get(key) != (r.review_status, r.reviewer_id) and r.reviewer_id not in authors:
            problems.append(f"{r.file}:{r.line}: {r.review_status} by {r.reviewer_id!r}, "
                            f"who is not an author of this PR ({', '.join(sorted(authors))})")
    return problems


@cli.command("check-reviewers")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--author", "authors", required=True, multiple=True,
              help="GitHub login of a PR author (opener or commit author); repeatable.")
@click.option("--base", "base_dir", type=click.Path(path_type=Path), default=None,
              help="Directory with the base branch's mapping files (same file names).")
def check_reviewers(paths: tuple[Path, ...], authors: tuple[str, ...], base_dir: Path | None) -> None:
    """Fail if a PR accepts/rejects mappings in someone else's name."""
    problems: list[str] = []
    for mf in read_mapping_files(list(paths)):
        base = base_dir / mf.path.name if base_dir else None
        base_rows = read_mapping_file(base).rows if base and base.exists() else []
        problems += unattributed_reviews(mf.rows, base_rows, set(authors))
    for p in problems:
        click.echo(f"ERROR {p}", err=True)
    click.echo(f"{len(problems)} review(s) not made by an author of this PR.")
    sys.exit(1 if problems else 0)


@cli.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--db", default="./registry.lbug", show_default=True)
@click.option("--registry-version", default="")
def load(paths: tuple[Path, ...], db: str, registry_version: str) -> None:
    """Load mapping files into the graph (run by pipeline.py after ingest)."""
    from db import get_connection
    conn = get_connection(db)
    rows: list = []
    for mf in read_mapping_files(list(paths)):
        for e in mf.errors:
            click.echo(f"WARNING {e} (skipped)", err=True)
        rows += mf.rows
    stats = load_rows(conn, rows, registry_version)
    for u in stats["unresolved"]:
        click.echo(f"WARNING unresolved reference {u} (skipped)", err=True)
    click.echo(f"Loaded {stats['loaded']} mapping(s) from {len(rows)} row(s).")


if __name__ == "__main__":
    cli()
