"""Shared lexical utilities (used by Stage 1 and Stage 2)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Domain abbreviation expansions. Extend via fixtures/tests, not ad hoc.
_EXPANSIONS: dict[str, str] = {
    "z": "redshift",
    "ra": "right ascension",
    "dec": "declination",
    "spec": "spectroscopic",
    "phot": "photometric",
    "mag": "magnitude",
    "err": "error",
    "vel": "velocity",
    "temp": "temperature",
    "obs": "observation",
    "coord": "coordinate",
    "id": "identifier",
}


def tokens(name: str) -> tuple[str, ...]:
    """snake/camel/kebab split, lowercased, abbreviations expanded."""
    s = _CAMEL.sub("_", name).replace("-", "_").replace(" ", "_").lower()
    out: list[str] = []
    for t in filter(None, s.split("_")):
        out.extend(_EXPANSIONS.get(t, t).split())
    return tuple(out)


def normalized(name: str) -> str:
    return " ".join(tokens(name))


def jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def string_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalized(a), normalized(b)).ratio()
