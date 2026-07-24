import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NEURO_GHOST_DIR = REPO_ROOT / "neuro_ghost"

# neuro_ghost/*.py use flat imports (e.g. `from db import ...`), the same way
# they resolve when run directly as `python neuro_ghost/ingest_linkml.py` —
# so neuro_ghost/ itself, not just the repo root, must be on sys.path.
for p in (str(REPO_ROOT), str(NEURO_GHOST_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
