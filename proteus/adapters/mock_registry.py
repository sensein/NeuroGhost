"""Fixture RegistryAdapter: reads schemas from YAML files.

Stands in for the real registry client until the upstream adapter is written.
YAML shape (see tests/fixtures/):

    schema_id: desi_cat
    elements:
      - id: z_spec
        kind: property
        name: z_spec
        aliases: [spec_z]
        definition: Spectroscopic redshift of the target.
        unit: ""
        exact_anchors: ["ivoa:src.redshift"]
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import yaml

from ..models import ElementRef, MatchingProfile


class YamlRegistry:
    def __init__(self, paths: Sequence[Path]):
        self._schemas: dict[str, list[MatchingProfile]] = {}
        for p in paths:
            data = yaml.safe_load(Path(p).read_text())
            sid = data["schema_id"]
            self._schemas[sid] = [self._profile(sid, e) for e in data["elements"]]

    @staticmethod
    def _profile(schema_id: str, e: dict) -> MatchingProfile:
        return MatchingProfile(
            ref=ElementRef(schema_id=schema_id, element_id=e["id"], kind=e.get("kind", "property")),
            name=e.get("name", e["id"]),
            aliases=tuple(e.get("aliases", [])),
            definition=e.get("definition", ""),
            parent_name=e.get("parent", ""),
            value_type=e.get("value_type", ""),
            unit=e.get("unit", ""),
            permissible_values=tuple(e.get("permissible_values", [])),
            exact_anchors=tuple(e.get("exact_anchors", [])),
            close_anchors=tuple(e.get("close_anchors", [])),
            broad_anchors=tuple(e.get("broad_anchors", [])),
        )

    def schema_ids(self) -> Sequence[str]:
        return list(self._schemas)

    def elements(self, schema_id: str) -> Iterable[MatchingProfile]:
        return list(self._schemas[schema_id])
