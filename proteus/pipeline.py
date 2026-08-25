"""Orchestrator — the only module that imports all stages.

Usage:
    python -m proteus.pipeline SCHEMA_A.yaml SCHEMA_B.yaml OUT.sssom.tsv
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

from . import stage1_blocking, stage2_signals, stage3_calibration, stage4_predicate, stage5_repair, stage6_write
from .adapters.mock_registry import YamlRegistry
from .interfaces import EmbeddingBackend, ReasonerBackend, RegistryAdapter
from .models import MappingSet
from .stage0_profiles import build_profiles


def run(
    registry: RegistryAdapter,
    subject_schema: str,
    object_schema: str,
    embedder: EmbeddingBackend | None = None,
    reasoner: ReasonerBackend | None = None,
) -> MappingSet:
    # Stage 0 — profiles (reasoner passed only when M2's enrichment exists)
    subjects = build_profiles(registry, subject_schema)
    objects = build_profiles(registry, object_schema)

    # Stage 1 — blocking + unit veto
    pairs, vetoes = stage1_blocking.generate_candidates(
        subjects, objects, embedder=embedder, reasoner=reasoner
    )

    # Stage 2 — signals; Stage 3 — combination; Stage 4 — predicates
    signals = stage2_signals.compute_all(pairs, reasoner=reasoner)
    scored = stage3_calibration.combine_all(signals)
    mappings = stage4_predicate.assign_all(scored)

    # Stage 5 — repair (structural sanity now; reasoner loop in M4)
    mappings = stage5_repair.repair(mappings, reasoner=None)

    return MappingSet(
        mapping_set_id=f"proteus:mapping-set/{uuid.uuid4()}",
        subject_schema=subject_schema,
        object_schema=object_schema,
        mappings=tuple(mappings),
        vetoes=tuple(vetoes),
        metadata={"pipeline_version": "0.1.0", "milestone": "M1", "calibrated": "false"},
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 3:
        print(__doc__)
        return 2
    a, b, out = argv
    registry = YamlRegistry([Path(a), Path(b)])
    ids = registry.schema_ids()
    mset = run(registry, ids[0], ids[1])
    stage6_write.write_sssom(mset, out)
    veto_path = stage6_write.write_veto_log(mset, Path(out).with_suffix(".vetoes.tsv"))
    print(f"{len(mset.mappings)} PROPOSED mappings -> {out}")
    print(f"{len(mset.vetoes)} vetoed pairs -> {veto_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
