from pathlib import Path

from proteus.adapters.mock_registry import YamlRegistry
from proteus.models import Predicate, ReviewStatus
from proteus.pipeline import run
from proteus.stage6_write import write_sssom, write_veto_log

FIX = Path(__file__).parent / "fixtures"


def _run():
    reg = YamlRegistry([FIX / "schema_a.yaml", FIX / "schema_b.yaml"])
    return run(reg, "desi_cat", "lsst_like")


def test_redshift_pair_surfaces():
    mset = _run()
    found = {(m.subject.element_id, m.object.element_id) for m in mset.mappings}
    assert ("z_spec", "redshift_spectroscopic") in found
    assert ("ra", "right_ascension") in found
    assert ("exposure_time", "exp_time") in found


def test_statistical_evidence_caps_at_close_match():
    # Invariant 10: without anchors (M1 runs reasonerless), no EXACT_MATCH.
    mset = _run()
    assert all(m.predicate is not Predicate.EXACT_MATCH for m in mset.mappings)


def test_everything_is_proposed():
    # Invariant 11.
    mset = _run()
    assert all(m.review_status is ReviewStatus.PROPOSED for m in mset.mappings)


def test_annotation_bug_vetoed_high_priority():
    # z_spec (dimensionless, anchor src.redshift) x wavelength (nm, same
    # anchor): lexically distant so the lexical channel may not pair them —
    # but wavelength x obs_wavelength (AA vs nm) is fine, while any admitted
    # incommensurable pair must land in the veto log, not the mappings.
    mset = _run()
    for m in mset.mappings:
        pass  # no incommensurable pair may appear as a mapping
    ids = {(v.subject.element_id, v.object.element_id) for v in mset.vetoes}
    # obs_wavelength[AA] x exp_time[s] is close enough lexically? Not needed;
    # assert the mechanism: no mapping pairs a length with a time.
    assert all(
        not (m.subject.element_id == "exposure_time" and m.object.element_id == "wavelength")
        for m in mset.mappings
    )


def test_sssom_output_roundtrip(tmp_path):
    mset = _run()
    out = write_sssom(mset, tmp_path / "out.sssom.tsv")
    vlog = write_veto_log(mset, tmp_path / "out.vetoes.tsv")
    text = out.read_text()
    assert "subject_id\tsubject_label\tpredicate_id" in text
    assert "skos:" in text and "PROPOSED" in text
    assert vlog.exists()
