"""Stage 6 — Write the MappingSet as SSSOM TSV, review_status=PROPOSED.

Invariant 11: the matcher never promotes its own output. Invariant 3: the
justification column preserves which evidence family produced each mapping.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .models import MappingSet

_COLUMNS = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "review_status",
    "comment",
]


def write_sssom(mset: MappingSet, path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="") as fh:
        # SSSOM metadata block as commented YAML header
        fh.write(f"# mapping_set_id: {mset.mapping_set_id}\n")
        fh.write(f"# subject_source: {mset.subject_schema}\n")
        fh.write(f"# object_source: {mset.object_schema}\n")
        for k, v in sorted(mset.metadata.items()):
            fh.write(f"# {k}: {v}\n")
        w = csv.writer(fh, delimiter="\t")
        w.writerow(_COLUMNS)
        for m in mset.mappings:
            w.writerow([
                f"{m.subject.schema_id}:{m.subject.element_id}",
                m.subject.element_id,
                m.predicate.value,
                f"{m.object.schema_id}:{m.object.element_id}",
                m.object.element_id,
                m.justification.value,
                f"{m.confidence:.4f}",
                m.review_status.value,
                m.comment,
            ])
    return path


def write_veto_log(mset: MappingSet, path: str | Path) -> Path:
    """Invariant 1: vetoed pairs are a data-quality audit artifact."""
    path = Path(path)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["priority", "subject_id", "object_id",
                    "subject_unit", "object_unit", "shared_anchor"])
        for v in sorted(mset.vetoes, key=lambda v: (v.priority != "HIGH", v.subject.element_id)):
            w.writerow([v.priority, v.subject.qualified, v.object.qualified,
                        v.subject_unit, v.object_unit, v.shared_anchor or ""])
    return path
