"""
mcp_server.py — NeuroGhost MCP server
--------------------------------------
Exposes the registry as MCP tools so any MCP-compatible chat system
(Claude Desktop, Cursor, etc.) can query, diff, transform, and ingest schemas.

Tools
-----
  list_sources          — all registered schemas + class counts
  search_classes        — name/definition search, optional source filter
  get_class             — full class detail (properties, alignments)
  get_alignments        — aligned classes across schemas with distance scores
  diff_schemas          — which classes are shared vs unique between two schemas
  transform_record      — map a data record from one schema to another
  get_provenance        — registry version changelog
  ingest_schema         — submit a new schema (opens GitHub issue)

Data source
-----------
Reads data/registry.json locally if present, otherwise fetches from the live
GitHub Pages URL. No database required.

Usage
-----
  # stdio (Claude Desktop / Cursor)
  python neuro_ghost/mcp_server.py

  # Inspect available tools
  mcp dev neuro_ghost/mcp_server.py

Claude Desktop config (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "neuroghost": {
        "command": "python",
        "args": ["/absolute/path/to/NeuroGhost/neuro_ghost/mcp_server.py"]
      }
    }
  }
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import os

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Paths / URLs
# ---------------------------------------------------------------------------

_ROOT            = Path(__file__).parent.parent
REGISTRY_PATH    = _ROOT / "data" / "registry.json"
PROVENANCE_PATH  = _ROOT / "data" / "provenance.json"
LIVE_REGISTRY    = os.environ.get(
    "NEUROGHOST_REGISTRY_URL",
    "https://sensein.group/NeuroGhost/data/registry.json",
)
LIVE_PROVENANCE  = "https://sensein.group/NeuroGhost/data/provenance.json"
GITHUB_ISSUES    = "https://api.github.com/repos/sensein/NeuroGhost/issues"
GITHUB_NEW_ISSUE = "https://github.com/sensein/NeuroGhost/issues/new"

# ---------------------------------------------------------------------------
# Registry cache
# ---------------------------------------------------------------------------

_registry: dict | None = None


def _load_registry() -> dict:
    global _registry
    if _registry is not None:
        return _registry
    if REGISTRY_PATH.exists():
        _registry = json.loads(REGISTRY_PATH.read_text())
    else:
        with urllib.request.urlopen(LIVE_REGISTRY, timeout=15) as r:
            _registry = json.loads(r.read())
    return _registry


def _classes() -> list[dict]:
    return _load_registry()["classes"]


def _sources() -> list[dict]:
    return _load_registry()["sources"]


def _class_index() -> dict[str, dict]:
    return {c["hash_id"]: c for c in _classes()}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "NeuroGhost",
    instructions=(
        "NeuroGhost is a shared vocabulary registry for neuroscience data. "
        "Use these tools to search concepts across schemas, compare schemas, "
        "transform data records between formats, and submit new schemas."
    ),
)


# ---------------------------------------------------------------------------
# Tool: list_sources
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sources() -> list[dict]:
    """List all registered schema sources with their class counts."""
    return _sources()


# ---------------------------------------------------------------------------
# Tool: search_classes
# ---------------------------------------------------------------------------

@mcp.tool()
def search_classes(
    query: str,
    source: str = "",
    limit: int = 20,
) -> list[dict]:
    """
    Search for classes by name or definition (case-insensitive substring match).

    Args:
        query:  Search string — matched against class name and definition.
        source: Optional schema label to restrict results (e.g. "bbqs", "bids").
        limit:  Max results to return (default 20).

    Returns a list of {name, hash_id, sources, iri, definition} dicts.
    """
    q = query.lower()
    results: list[dict] = []
    for c in _classes():
        if source and source not in c.get("sources", []):
            continue
        if q in c["name"].lower() or q in (c.get("definition") or "").lower():
            results.append({
                "name":       c["name"],
                "hash_id":    c["hash_id"],
                "iri":        c.get("iri", ""),
                "sources":    c.get("sources", []),
                "definition": (c.get("definition") or "")[:300],
            })
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Tool: get_class
# ---------------------------------------------------------------------------

@mcp.tool()
def get_class(name_or_hash: str) -> dict | None:
    """
    Get full detail for a class — properties, alignments, sources, IRI.

    Args:
        name_or_hash: Class name (case-insensitive, partial ok) or exact hash_id.

    Returns the full class dict or null if not found.
    """
    q = name_or_hash.lower()
    for c in _classes():
        if c["hash_id"] == name_or_hash or q in c["name"].lower():
            return c
    return None


# ---------------------------------------------------------------------------
# Tool: get_alignments
# ---------------------------------------------------------------------------

@mcp.tool()
def get_alignments(
    class_name: str,
    max_distance: float = 0.5,
) -> list[dict]:
    """
    Get classes aligned to a given class across all registered schemas.

    Distance: 0.0 = identical, 1.0 = unrelated.

    Args:
        class_name:   Name or hash_id of the source class.
        max_distance: Only return alignments closer than this (default 0.5).

    Returns a list of aligned classes sorted by distance, each with
    {name, sources, distance, method, scores, definition}.
    """
    c = get_class(class_name)
    if c is None:
        return []

    index = _class_index()
    results: list[dict] = []
    for a in c.get("alignments", []):
        if a["distance"] > max_distance:
            continue
        target = index.get(a["target_hash_id"], {})
        results.append({
            "name":       a.get("target_name", ""),
            "hash_id":    a.get("target_hash_id", ""),
            "sources":    target.get("sources", []),
            "distance":   a["distance"],
            "method":     a.get("method", ""),
            "scores":     a.get("scores", {}),
            "definition": (target.get("definition") or "")[:300],
        })
    results.sort(key=lambda x: x["distance"])
    return results


# ---------------------------------------------------------------------------
# Tool: diff_schemas
# ---------------------------------------------------------------------------

@mcp.tool()
def diff_schemas(source_a: str, source_b: str) -> dict:
    """
    Compare two schemas — which classes overlap and which are unique to each.

    Args:
        source_a: Label of the first schema (e.g. "bbqs").
        source_b: Label of the second schema (e.g. "bids").

    Returns:
        only_in_<source_a>: classes found only in source_a
        only_in_<source_b>: classes found only in source_b
        shared: [{a_name, b_name, distance}] — best cross-schema alignment
    """
    a_classes = [c for c in _classes() if source_a in c.get("sources", [])]
    b_classes = [c for c in _classes() if source_b in c.get("sources", [])]
    b_index   = {c["hash_id"]: c for c in b_classes}

    only_a: list[str] = []
    only_b: list[str] = []
    shared: list[dict] = []
    matched_b: set[str] = set()

    for c in a_classes:
        aligned_to_b = [
            a for a in c.get("alignments", [])
            if a["target_hash_id"] in b_index
        ]
        if aligned_to_b:
            best = min(aligned_to_b, key=lambda x: x["distance"])
            shared.append({
                "a_name":   c["name"],
                "b_name":   best["target_name"],
                "distance": best["distance"],
            })
            matched_b.add(best["target_hash_id"])
        else:
            only_a.append(c["name"])

    for c in b_classes:
        if c["hash_id"] not in matched_b:
            only_b.append(c["name"])

    shared.sort(key=lambda x: x["distance"])
    return {
        f"only_in_{source_a}": sorted(only_a),
        f"only_in_{source_b}": sorted(only_b),
        "shared":              shared,
    }


# ---------------------------------------------------------------------------
# Tool: transform_record
# ---------------------------------------------------------------------------

@mcp.tool()
def transform_record(
    source_schema: str,
    target_schema: str,
    record: dict,
) -> dict:
    """
    Transform a data record from one schema to another using alignment edges.

    Looks up the class in source_schema whose properties best match the record's
    fields, then follows alignment edges to the closest class in target_schema,
    and maps property names across.

    Args:
        source_schema: Schema the record comes from (e.g. "bbqs").
        target_schema: Schema to map to (e.g. "bids").
        record:        Dict of {field_name: value} in source_schema format.

    Returns:
        mapped:   {target_field: value} — successfully remapped fields
        unmapped: [field_names] — fields with no alignment found
        warnings: human-readable notes
    """
    src_classes = [c for c in _classes() if source_schema in c.get("sources", [])]
    tgt_index   = {c["hash_id"]: c for c in _classes() if target_schema in c.get("sources", [])}

    # Build property map: source_prop_name (lower) -> target_prop_name
    prop_map: dict[str, str] = {}

    for src_c in src_classes:
        for align in src_c.get("alignments", []):
            if align["distance"] > 0.6:
                continue
            tgt_c = tgt_index.get(align["target_hash_id"])
            if not tgt_c:
                continue
            tgt_props = {p["name"].lower(): p["name"] for p in tgt_c.get("properties", [])}
            for src_p in src_c.get("properties", []):
                src_lower = src_p["name"].lower()
                if src_lower in tgt_props:
                    prop_map[src_lower] = tgt_props[src_lower]

    mapped: dict[str, Any] = {}
    unmapped: list[str]    = []

    for field, value in record.items():
        target_field = prop_map.get(field.lower())
        if target_field:
            mapped[target_field] = value
        else:
            unmapped.append(field)

    warnings: list[str] = []
    if unmapped:
        warnings.append(
            f"{len(unmapped)} field(s) had no alignment: {', '.join(unmapped)}"
        )
    if not prop_map:
        warnings.append(
            f"No property alignments found between '{source_schema}' and "
            f"'{target_schema}'. Run align.py to compute cross-schema edges."
        )

    return {"mapped": mapped, "unmapped": unmapped, "warnings": warnings}


# ---------------------------------------------------------------------------
# Tool: get_provenance
# ---------------------------------------------------------------------------

@mcp.tool()
def get_provenance() -> list[dict]:
    """
    Get the full changelog of registry versions — every schema ingestion,
    bump type, triggering issue, and class count at each version.
    """
    if PROVENANCE_PATH.exists():
        data = json.loads(PROVENANCE_PATH.read_text())
    else:
        with urllib.request.urlopen(LIVE_PROVENANCE, timeout=15) as r:
            data = json.loads(r.read())
    return data if isinstance(data, list) else data.get("entries", [])


# ---------------------------------------------------------------------------
# Tool: ingest_schema
# ---------------------------------------------------------------------------

@mcp.tool()
def ingest_schema(
    schema_yaml: str,
    schema_name: str,
    github_token: str = "",
) -> dict:
    """
    Submit a new schema to the NeuroGhost registry.

    With a GitHub token (repo scope): opens an issue directly via API.
    Without a token: returns a pre-filled GitHub issue URL to open manually.

    The CI workflow validates, ingests, aligns, and archives the schema within
    a few minutes of the issue being opened.

    Args:
        schema_yaml:   LinkML YAML content of the schema.
        schema_name:   Human-readable name for the schema (e.g. "my-lab-schema").
        github_token:  GitHub personal access token with 'repo' scope (optional).

    Returns:
        { status: "created" | "manual", issue_url: str }
    """
    title = f"[schema] {schema_name}"
    body  = (
        f"## Schema submission: {schema_name}\n\n"
        f"```yaml\n{schema_yaml}\n```\n\n"
        "_Submitted via NeuroGhost MCP server._"
    )

    if not github_token:
        params = urllib.parse.urlencode({"title": title, "body": body})
        url    = f"{GITHUB_NEW_ISSUE}?{params}"
        return {"status": "manual", "issue_url": url}

    payload = json.dumps({"title": title, "body": body}).encode()
    req = urllib.request.Request(
        GITHUB_ISSUES,
        data=payload,
        headers={
            "Authorization": f"token {github_token}",
            "Accept":        "application/vnd.github+json",
            "Content-Type":  "application/json",
            "User-Agent":    "NeuroGhost-MCP/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return {"status": "created", "issue_url": resp["html_url"]}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the `neuroghost-mcp` console script.

    Transport is selected by the MCP_TRANSPORT env var:
      stdio (default) — for Claude Desktop / Cursor / local use
      sse             — HTTP+SSE for Smithery and other hosted platforms
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
