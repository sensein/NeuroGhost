"""Unit canonicalization and the unit veto.

Invariant 1: the veto is a hard filter, never a score, and vetoed pairs are
logged. The strongest single filter in the system: an embedding model can be
seduced by suggestive prose; dimensional analysis cannot.

Milestone 1 ships a small built-in UCUM-ish table sufficient for the fixtures.
The real system should canonicalize via QUDT lookup; extend `_TABLE` or swap in
a QUDT resolver behind the same two functions.
"""
from __future__ import annotations

from .models import DimensionVector, MatchingProfile, VetoRecord

_D = DimensionVector

# UCUM-ish unit string -> QUDT dimension vector (L, M, T, I, Θ, N, J)
_TABLE: dict[str, DimensionVector] = {
    "": _D(),  # dimensionless
    "1": _D(),
    "dimensionless": _D(),
    "m": _D(L=1),
    "km": _D(L=1),
    "Mpc": _D(L=1),
    "pc": _D(L=1),
    "AA": _D(L=1),  # Ångström (UCUM)
    "angstrom": _D(L=1),
    "nm": _D(L=1),
    "s": _D(T=1),
    "yr": _D(T=1),
    "Gyr": _D(T=1),
    "kg": _D(M=1),
    "Msun": _D(M=1),
    "solMass": _D(M=1),
    "deg": _D(),  # plane angle: dimensionless in QUDT terms
    "arcsec": _D(),
    "rad": _D(),
    "Hz": _D(T=-1),
    "km/s": _D(L=1, T=-1),
    "m/s": _D(L=1, T=-1),
    "km/s/Mpc": _D(T=-1),  # Hubble parameter units reduce to 1/time
    "Jy": _D(M=1, T=-2),  # W m^-2 Hz^-1
    "mag": _D(),  # logarithmic flux ratio: treated dimensionless
    "K": _D(THETA=1),
    "eV": _D(L=2, M=1, T=-2),
    "erg": _D(L=2, M=1, T=-2),
}


def dimension_of(unit: str) -> DimensionVector | None:
    """Canonical dimension vector for a unit string, or None if unknown.

    Unknown is *unknown*, not dimensionless — an unknown unit must never
    trigger the veto (that would violate blocking's recall guarantee).
    """
    return _TABLE.get(unit.strip())


def veto(subject: MatchingProfile, object: MatchingProfile) -> VetoRecord | None:
    """Return a VetoRecord if the pair is dimensionally incommensurable,
    else None. Only fires when BOTH sides have known dimensions."""
    ds, do = subject.unit.dimension, object.unit.dimension
    if ds is None or do is None:
        return None
    if ds.compatible(do):
        return None
    shared = set(subject.exact_anchors) & set(object.exact_anchors)
    return VetoRecord(
        subject=subject.ref,
        object=object.ref,
        subject_unit=subject.unit.ucum_code,
        object_unit=object.unit.ucum_code,
        shared_anchor=next(iter(sorted(shared)), None),
    )


def unit_compatibility(subject: MatchingProfile, object: MatchingProfile) -> bool | None:
    """Soft residual feature for Stage 2: True if compatible, None if unknown
    on either side (missing, not zero — invariant 4). Never False here: the
    False case was already vetoed in Stage 1."""
    if subject.unit.dimension is None or object.unit.dimension is None:
        return None
    return subject.unit.dimension.compatible(object.unit.dimension)
