#!/usr/bin/env python3
"""
Reject a submitted schema whose content is already in the registry.

Given a target schema file, compute its file-level content hash (the same
canonicalised SHA-256 used for SchemaSource.content_hash) and compare it
against every OTHER schema already committed in the same directory
(registry_schemas/). If an identical file exists, exit non-zero and name it —
so the CI ingestion workflow fails early with a clear message instead of
silently ingesting a duplicate.

Usage:
    python scripts/check_duplicate_schema.py registry_schemas/<name>.yml
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "neuro_ghost"))
from schema_hash import content_hash  # noqa: E402


def find_duplicate(target: Path) -> Path | None:
    """Return a sibling schema file with content identical to `target`, or None."""
    target = target.resolve()
    target_hash = content_hash(target.read_text())
    for other in sorted(target.parent.glob("*.yml")):
        if other.name == "meta_model.yaml" or other.resolve() == target:
            continue
        if content_hash(other.read_text()) == target_hash:
            return other
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_duplicate_schema.py <schema.yml>", file=sys.stderr)
        return 2
    target = Path(argv[1])
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2

    dup = find_duplicate(target)
    if dup:
        print(
            f"❌ '{target.name}' is identical to '{dup.name}', which is already "
            f"in the registry. This schema is already added — nothing to ingest.",
            file=sys.stderr,
        )
        return 1

    print(f"✓ '{target.name}' is not a duplicate of any existing schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
