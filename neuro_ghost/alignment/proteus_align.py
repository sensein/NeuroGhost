"""
proteus_align.py — Proteus alignment module caller
====================================================

Delegates to the external `proteus` package (neurovium/Proteus).
Install it with:  pip install git+https://github.com/neurovium/Proteus.git

Usage
-----
  from neuro_ghost.alignment.proteus_align import compute_alignment, BACKEND

  result = compute_alignment(class_a, class_b)
  print(BACKEND)  # "proteus-package"
"""

from __future__ import annotations

try:
    from proteus.align import compute_alignment   # type: ignore
    from proteus.align import repair_structural   # type: ignore
    from proteus.align import write_alignment     # type: ignore
    BACKEND = "proteus-package"
except ImportError as exc:
    raise ImportError(
        "The Proteus alignment package is not installed.\n"
        "Install it with:\n"
        "  pip install git+https://github.com/neurovium/Proteus.git"
    ) from exc

__all__ = ["compute_alignment", "repair_structural", "write_alignment", "BACKEND"]
