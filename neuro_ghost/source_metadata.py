"""
source_metadata.py — per-schema source-metadata sidecar
=======================================================
A schema may ship an OPTIONAL sidecar file next to it, named
`<schema_stem>_source.yaml` (or `.yml`), carrying metadata that the LinkML/JSON
schema itself has no standard place for:

    registry_schemas/dandiset.yml
    registry_schemas/dandiset_source.yaml

The sidecar is a flat mapping. A key routes by a `bundle_` PREFIX (see
ingest_linkml._split_metadata):

  * `bundle_`-prefixed keys → the **SchemaBundle** (the logical schema), with the
    prefix stripped: `bundle_label` (the umbrella name shared by a multi-file
    schema's files), `bundle_title`, `bundle_homepage`, `bundle_publisher`,
    `bundle_contact`, `bundle_license`, `bundle_description`.
  * bare keys → the per-file **SchemaSource**: `source_id`, `source_iri`,
    `source_version`, and its own `title` / `description` / `homepage`.

So a bare `homepage:` documents the individual file, while `bundle_homepage:`
documents the whole bundle. Example (one file of the multi-file DANDI schema):

    bundle_label: dandi                          # groups asset + dandiset
    bundle_title: DANDI Schema                   # SchemaBundle.title
    bundle_homepage: https://www.dandiarchive.org/
    source_id: https://github.com/dandi/schema   # this file's own provenance
    source_version: 0.8.0

Per-file `title` / `description` / `source_id` are also *propagated* from the
schema's own `title:` / `description:` / `id:` when the sidecar doesn't set them.
Unknown keys are ignored (ensure_schema_bundle/ensure_schema_source only write
their own slots). Absent sidecar → those fields are simply blank.
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
