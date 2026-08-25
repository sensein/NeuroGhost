from proteus.models import DimensionVector, ElementRef, MatchingProfile
from proteus.units import dimension_of, unit_compatibility, veto


def _prof(eid, unit, anchors=()):
    return MatchingProfile(
        ref=ElementRef(schema_id="s", element_id=eid, kind="property"),
        name=eid, unit=unit, dimension=dimension_of(unit),
        exact_anchors=tuple(anchors),
    )


def test_incommensurable_dimensions_veto():
    v = veto(_prof("wavelength", "AA"), _prof("exposure", "s"))
    assert v is not None and v.priority == "NORMAL"


def test_unknown_unit_never_vetoes():
    # Recall guard: unknown is unknown, not dimensionless.
    assert veto(_prof("x", "furlongs_per_fortnight"), _prof("y", "s")) is None


def test_shared_anchor_conflict_is_high_priority():
    v = veto(
        _prof("z", "", anchors=["ivoa:src.redshift"]),
        _prof("wavelength", "nm", anchors=["ivoa:src.redshift"]),
    )
    assert v is not None and v.priority == "HIGH"
    assert v.shared_anchor == "ivoa:src.redshift"


def test_compatibility_missing_is_none_not_false():
    assert unit_compatibility(_prof("a", "unknown_unit"), _prof("b", "s")) is None
    assert unit_compatibility(_prof("a", "km"), _prof("b", "Mpc")) is True


def test_reduced_dimensions():
    assert dimension_of("km/s/Mpc") == dimension_of("Hz") == DimensionVector(T=-1)
