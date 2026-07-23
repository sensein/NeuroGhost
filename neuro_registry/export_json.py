"""
export_json.py — Export registry snapshot to data/registry.json
---------------------------------------------------------------
Reads the LadybugDB graph and writes a single JSON file that the
GitHub Pages frontend consumes. Runs as the last step in the CI
workflow after every schema ingestion.

Output shape:
{
  "generated_at": "2025-...",
  "sources": [
    { "label": "schema.org", "version": "1.0.0", "class_count": 38 }
  ],
  "classes": [
    {
      "uid":          "...",
      "iri":          "https://schema.org/Person",
      "uri":          "https://registry.sensein.io/obj/Person/v/1.0.0",
      "name":         "Person",
      "definition":   "A person...",
      "version":      "1.0.0",
      "abstract":     false,
      "source":       "schema.org",
      "properties":   [
        {
          "uid":         "...",
          "iri":         "https://schema.org/name",
          "name":        "name",
          "definition":  "...",
          "datatype":    "xsd:string",
          "range_uri":   "",
          "multivalued": false,
          "required":    false,
          "source":      "schema.org"
        }
      ],
      "subclass_of":  ["https://schema.org/Thing"],
      "alignments":   [
        {
          "target_uid":  "...",
          "target_name": "Investigator",
          "target_iri":  "https://schema.org/Person",
          "target_source": "bbqs",
          "distance":    0.0,
          "method":      "iri"
        }
      ]
    }
  ]
}

Usage:
    python export_json.py
    python export_json.py --db ./registry.lbug --out data/registry.json
"""

from __future__ import annotations
import datetime, json, os
from pathlib import Path

import click
import ladybug as lb

DB_PATH  = "./registry.lbug"
OUT_PATH = "data/registry.json"


def export(conn: lb.Connection) -> dict:
    # ---- sources -----------------------------------------------------------
    src_result = conn.execute(
        "MATCH (s:SchemaSource) RETURN s.uid, s.label, s.version"
    )
    source_rows = src_result.get_all()

    source_class_counts: dict[str, int] = {}
    for row in source_rows:
        _, label, _ = row
        r = conn.execute(
            "MATCH (n:SchemaClass {source_label: $src}) RETURN count(n)",
            {"src": label}
        )
        source_class_counts[label] = r.get_next()[0]

    sources = [
        {
            "label":       row[1],
            "version":     row[2] or "1.0.0",
            "class_count": source_class_counts.get(row[1], 0),
        }
        for row in source_rows
    ]

    # ---- classes -----------------------------------------------------------
    cls_result = conn.execute("""
        MATCH (n:SchemaClass)
        RETURN n.uid, n.iri, n.uri, n.name, n.definition,
               n.version, n.abstract, n.source_label
        ORDER BY n.source_label, n.name
    """)

    classes = []
    for row in cls_result.get_all():
        uid, iri, uri, name, definition, version, abstract, source = row

        # properties
        prop_result = conn.execute("""
            MATCH (c:SchemaClass {uid: $uid})-[:HAS_PROPERTY]->(p:SchemaProperty)
            RETURN p.uid, p.iri, p.name, p.definition,
                   p.datatype, p.range_uri, p.multivalued,
                   p.required, p.source_label
            ORDER BY p.name
        """, {"uid": uid})

        properties = [
            {
                "uid":         r[0],
                "iri":         r[1] or "",
                "name":        r[2] or "",
                "definition":  r[3] or "",
                "datatype":    r[4] or "",
                "range_uri":   r[5] or "",
                "multivalued": bool(r[6]),
                "required":    bool(r[7]),
                "source":      r[8] or "",
            }
            for r in prop_result.get_all()
        ]

        # subclass_of
        sub_result = conn.execute("""
            MATCH (c:SchemaClass {uid: $uid})-[:SUBCLASS_OF]->(p:SchemaClass)
            RETURN p.iri
        """, {"uid": uid})
        subclass_of = [r[0] for r in sub_result.get_all() if r[0]]

        # alignments
        align_result = conn.execute("""
            MATCH (c:SchemaClass {uid: $uid})-[a:ALIGNED_TO]->(t:SchemaClass)
            RETURN t.uid, t.name, t.iri, t.source_label, a.distance, a.method
            ORDER BY a.distance
        """, {"uid": uid})

        alignments = [
            {
                "target_uid":    r[0],
                "target_name":   r[1] or "",
                "target_iri":    r[2] or "",
                "target_source": r[3] or "",
                "distance":      float(r[4]) if r[4] is not None else 1.0,
                "method":        r[5] or "",
            }
            for r in align_result.get_all()
        ]

        classes.append({
            "uid":         uid,
            "iri":         iri or "",
            "uri":         uri or "",
            "name":        name or "",
            "definition":  definition or "",
            "version":     version or "1.0.0",
            "abstract":    bool(abstract),
            "source":      source or "",
            "properties":  properties,
            "subclass_of": subclass_of,
            "alignments":  alignments,
        })

    return {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "sources":      sources,
        "classes":      classes,
    }


@click.command()
@click.option("--db",  default=DB_PATH,  show_default=True,
              help="Path to LadybugDB file.")
@click.option("--out", default=OUT_PATH, show_default=True,
              help="Output JSON path.")
def cli(db: str, out: str) -> None:
    """Export registry snapshot to JSON for the GitHub Pages frontend."""
    conn = lb.Connection(lb.Database(db))
    data = export(conn)

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2))

    nc = len(data["classes"])
    ns = len(data["sources"])
    click.echo(f"Exported {nc} classes from {ns} sources → {out_path}")


if __name__ == "__main__":
    cli()
