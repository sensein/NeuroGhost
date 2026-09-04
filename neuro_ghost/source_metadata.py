"""
source_metadata.py — per-schema source-metadata sidecar
=======================================================
Schema-level descriptive metadata lives on the SchemaBundle (the logical
schema), not the per-file SchemaSource. Most of it is *propagated* from the
ingested schema itself: `ensure_schema_bundle()` sets `title`, `description`,
`source_id`, `license` and `source_iri` from the schema's own
`title:` / `description:` / `id:` / `license:` (see parse_linkml's `meta`). That's
the path that matters going forward — as real schemas replace the current test
set, their metadata comes along for free.

For fields a LinkML/JSON schema has no standard place for — `homepage`,
`publisher`, `contact` — a schema may ship an OPTIONAL sidecar file next to it,
named `<schema_stem>_source.yaml` (or `.yml`):

    registry_schemas/dandi.yml
    registry_schemas/dandi_source.yaml

The sidecar is a flat mapping whose keys are SchemaBundle slot names:

    homepage: https://www.dandiarchive.org/    # SchemaBundle.homepage (uri)
    publisher: DANDI Team                       # SchemaBundle.publisher
    contact: help@dandiarchive.org              # SchemaBundle.contact
    # may also override the propagated title / description / source_id /
    # source_iri / source_version / license, and set bundle_label for a
    # multi-file schema (the umbrella name shared by its files)

Unknown keys are ignored (ensure_schema_bundle/ensure_schema_source only write
their own slots). It's discovered automatically at ingest and merged over the
propagated fields; the web UI's ingest flow can submit the same content
alongside a schema. Absent sidecar → those fields are simply blank.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def sidecar_candidates(schema_path: str | Path) -> list[Path]:
    """Candidate sidecar paths for a schema file, in preference order:
    `<dir>/<stem>_source.yaml` then `<dir>/<stem>_source.yml`."""
    p = Path(schema_path)
    return [p.with_name(f"{p.stem}_source.yaml"),
            p.with_name(f"{p.stem}_source.yml")]


def load_source_sidecar(schema_path: str | Path) -> dict[str, Any]:
    """Load the `<stem>_source.yaml` (or `.yml`) sidecar next to the schema, or
    {} if none exists (or it's empty / not a mapping)."""
    for sc in sidecar_candidates(schema_path):
        if sc.exists():
            data = yaml.safe_load(sc.read_text()) or {}
            return data if isinstance(data, dict) else {}
    return {}
