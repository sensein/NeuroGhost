"""
align.py — Proteus-aligned semantic alignment for NeuroGhost
=============================================================

Implements the Proteus alignment pipeline
(https://github.com/neurovium/Proteus/tree/main/proteus-align)
inline — no external proteus_align import required.

PIPELINE STAGES
---------------
Stage 0  load_classes()           — build MatchingProfiles from LadybugDB
Stage 1  pairs_across_sources()   — blocking: recall-focused candidate pairs
         + unit veto              — the ONLY precision filter at this stage
Stage 2  compute_signals()        — SignalVector per pair
Stage 3  calibrate()              — confidence score + evidence regime
Stage 4  assign_predicate()       — SKOS predicate with pathway invariant
Stage 5  repair_structural()      — demote duplicate exactMatches
Stage 6  write_alignment()        — ALIGNED_TO edge in LadybugDB

KEY INVARIANTS (from Proteus CLAUDE.md)
----------------------------------------
1. Unit dimension compatibility is a hard VETO, never a scoring factor.
2. Blocking is tuned for recall; everything after is for precision.
3. Missing data is MISSING (None), never zero-imputed.
4. Only anchored evidence (IRI / ontology) can yield skos:exactMatch.
   Statistical evidence alone caps at skos:closeMatch.
5. Structural repair demotes, never deletes.

SIGNAL WEIGHTS (M1 calibration)
---------------------------------
  name_similarity : 0.45  (token Jaccard + string similarity, take max)
  token_jaccard   : 0.35  (set overlap of camelCase-split tokens)
  alias_overlap   : 0.20  (best alias pair similarity — MISSING if no aliases)
  definition      : bonus (25% blend when embeddings available)
  unit_compatible : +0.05 bonus capped at 1.0

DEFINITION EMBEDDINGS (M3 — implemented)
-----------------------------------------
We implement definition similarity via sentence-transformers
(all-MiniLM-L6-v2). This is an advance on the Proteus skeleton, which
marks M3 as MISSING pending completion. Embeddings are cached in
data/embeddings.parquet so CI doesn't recompute from scratch.

USAGE
-----
  python align.py                           # align all source pairs
  python align.py --source bbqs            # align bbqs against all others
  python align.py --dry-run               # print pairs without writing
  python align.py --threshold 0.5         # only write edges with d <= 0.5
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Iterator

import click

from db import get_connection

# ---------------------------------------------------------------------------
# Confidence thresholds (Proteus stage 4)
# ---------------------------------------------------------------------------

EXACT_CONF    = 0.95   # anchored only
BROAD_CONF    = 0.85   # anchored broad/narrow
CLOSE_CONF    = 0.65   # statistical ceiling
RELATED_FLOOR = 0.45   # drop anything below this

# Stage 3 weights (Proteus M1)
W_NAME    = 0.45
W_JACCARD = 0.35
W_ALIAS   = 0.20
UNIT_BONUS = 0.05

MISSING = None  # sentinel: signal absent, not zero (Invariant 3)

DB_PATH          = "./registry.lbug"
EMBEDDINGS_PATH  = Path("data/embeddings.parquet")


# ---------------------------------------------------------------------------
# Inline _lexical.py — tokenization & similarity (Proteus)
# ---------------------------------------------------------------------------

# Domain abbreviations. Extend via tests, not ad hoc.
_ABBREV: dict[str, str] = {
    "subj": "subject",  "obj": "object",    "desc": "description",
    "def":  "definition","prop": "property", "cls":  "class",
    "uri":  "identifier","iri": "identifier","id":   "identifier",
    "src":  "source",   "tgt": "target",    "ver":  "version",
    "num":  "number",   "cnt": "count",     "freq": "frequency",
    "temp": "temperature","samp": "sample",  "rec":  "recording",
    "subtype": "subtype","idx": "index",
}


def _tokens(name: str) -> tuple[str, ...]:
    """Split name into normalised tokens (camelCase, snake_case, kebab-case)."""
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    parts = re.split(r"[\s_\-/]+", s.lower())
    return tuple(_ABBREV.get(p, p) for p in parts if p)


def _jaccard(a: str, b: str) -> float:
    """Token Jaccard similarity between two names."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def _string_sim(a: str, b: str) -> float:
    """Edit-distance similarity on normalised strings (0–1)."""
    if not a or not b:
        return 0.0
    na = " ".join(_tokens(a))
    nb = " ".join(_tokens(b))
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _alias_best(names_a: list[str], names_b: list[str]) -> float | None:
    """Best pairwise string similarity across two alias lists. MISSING if empty."""
    if not names_a or not names_b:
        return MISSING
    return max(_string_sim(a, b) for a in names_a for b in names_b)


# ---------------------------------------------------------------------------
# Inline units.py — dimensional veto (Proteus)
# ---------------------------------------------------------------------------
# UCUM → QUDT dimension vector: (L, M, T, I, Θ, N, J)
# None = unknown unit — never veto on unknown.

_DIMS: dict[str, tuple[int, ...]] = {
    # dimensionless
    "1": (0,0,0,0,0,0,0), "ratio": (0,0,0,0,0,0,0), "percent": (0,0,0,0,0,0,0),
    # length
    "m": (1,0,0,0,0,0,0), "mm": (1,0,0,0,0,0,0), "cm": (1,0,0,0,0,0,0),
    "km": (1,0,0,0,0,0,0), "um": (1,0,0,0,0,0,0), "nm": (1,0,0,0,0,0,0),
    # time
    "s": (0,0,1,0,0,0,0), "ms": (0,0,1,0,0,0,0), "us": (0,0,1,0,0,0,0),
    "min": (0,0,1,0,0,0,0), "h": (0,0,1,0,0,0,0),
    "hour": (0,0,1,0,0,0,0), "day": (0,0,1,0,0,0,0),
    # frequency
    "hz": (0,0,-1,0,0,0,0), "khz": (0,0,-1,0,0,0,0),
    # temperature (celsius/kelvin/fahrenheit share dimension Θ)
    "k": (0,0,0,0,1,0,0), "celsius": (0,0,0,0,1,0,0),
    "degc": (0,0,0,0,1,0,0), "fahrenheit": (0,0,0,0,1,0,0),
    # mass
    "kg": (0,1,0,0,0,0,0), "g": (0,1,0,0,0,0,0), "mg": (0,1,0,0,0,0,0),
    # electrical
    "v": (2,1,-3,-1,0,0,0), "mv": (2,1,-3,-1,0,0,0), "uv": (2,1,-3,-1,0,0,0),
    "a": (0,0,0,1,0,0,0),  "ma": (0,0,0,1,0,0,0),
    "ohm": (2,1,-3,-2,0,0,0),
    # amount
    "mol": (0,0,0,0,0,1,0), "mmol": (0,0,0,0,0,1,0),
}


def _dimension_of(unit: str) -> tuple[int, ...] | None:
    return _DIMS.get(unit.lower().strip())


def _unit_veto(units_a: list[str], units_b: list[str]) -> bool:
    """
    Hard veto: return True when BOTH sides have known but incompatible dimensions.
    Only fires when dimensions are known on both sides (Invariant 1).
    """
    for ua in units_a:
        da = _dimension_of(ua)
        if da is None:
            continue
        for ub in units_b:
            db = _dimension_of(ub)
            if db is None:
                continue
            if da != db:
                return True
    return False


def _unit_compatible(units_a: list[str], units_b: list[str]) -> bool | None:
    """Soft compatibility for stage 3 bonus. None = unknown on at least one side."""
    known_a = [_dimension_of(u) for u in units_a if _dimension_of(u) is not None]
    known_b = [_dimension_of(u) for u in units_b if _dimension_of(u) is not None]
    if not known_a or not known_b:
        return None
    return known_a[0] == known_b[0]


# ---------------------------------------------------------------------------
# Embedding model — lazy loaded, cached globally (implements M3)
# ---------------------------------------------------------------------------

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            click.echo("  Loaded sentence-transformers all-MiniLM-L6-v2")
        except Exception as e:
            _model = "fallback"
            click.echo(
                f"  Could not load sentence-transformers ({type(e).__name__}) — "
                "falling back to string_sim.\n"
                "  Fix: pip install 'sentence-transformers>=2.7.0,<3.0.0'"
            )
    return _model


def _load_embedding_cache() -> dict[str, list[float]]:
    if not EMBEDDINGS_PATH.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_parquet(EMBEDDINGS_PATH)
        return {row["text"]: row["embedding"] for _, row in df.iterrows()}
    except Exception as e:
        click.echo(f"  WARNING: could not load embedding cache — {e}")
        return {}


def _save_embedding_cache(cache: dict[str, list[float]]) -> None:
    try:
        import pandas as pd
        EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([{"text": t, "embedding": e} for t, e in cache.items()])
        df.to_parquet(EMBEDDINGS_PATH, index=False)
        click.echo(f"  Saved {len(cache)} embeddings → {EMBEDDINGS_PATH}")
    except Exception as e:
        click.echo(f"  WARNING: could not save embedding cache — {e}")


_embedding_cache: dict[str, list[float]] = {}
_cache_dirty = False


def _embed(text: str) -> list[float] | None:
    global _embedding_cache, _cache_dirty
    if not _embedding_cache:
        _embedding_cache = _load_embedding_cache()
    if not text or not text.strip():
        return None
    if text in _embedding_cache:
        return _embedding_cache[text]
    model = _get_model()
    if model == "fallback":
        return None
    emb = model.encode([text], normalize_embeddings=True)[0].tolist()
    _embedding_cache[text] = emb
    _cache_dirty = True
    return emb


def _cosine(text_a: str, text_b: str) -> float | None:
    """Cosine similarity via embeddings (M3). None if model unavailable."""
    ea, eb = _embed(text_a), _embed(text_b)
    if ea is None or eb is None:
        return MISSING
    import numpy as np
    return float(np.dot(ea, eb))


# ---------------------------------------------------------------------------
# Stage 2 — SignalVector
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalVector:
    """
    Per-pair evidence bundle (Proteus stage 2).
    Each field is None (MISSING) when the signal is absent — never zero-imputed.
    """
    name_similarity: float | None   # max(jaccard, string_sim) on names
    token_jaccard:   float | None   # set-based token overlap
    alias_overlap:   float | None   # best alias pair similarity (MISSING if no aliases)
    def_similarity:  float | None   # cosine on definitions (M3 — implemented)
    unit_compatible: bool  | None   # dimensional compat; None = unknown
    anchor_relation: str   | None   # "identical"|"broader"|"narrower"|"unrelated"|None


def _anchor_relation(
    iri_a: str, iri_b: str,
    parents_a: list[str], parents_b: list[str],
) -> str | None:
    """Classify ontology anchor relationship (Proteus stage 2, M2 stub)."""
    if not iri_a or not iri_b:
        return MISSING
    a, b = iri_a.rstrip("/"), iri_b.rstrip("/")
    if a == b:
        return "identical"
    if b in [p.rstrip("/") for p in parents_a]:
        return "broader"   # B is parent of A → A is narrower → use broadMatch
    if a in [p.rstrip("/") for p in parents_b]:
        return "narrower"
    return "unrelated"


def compute_signals(a: dict, b: dict) -> SignalVector:
    """Stage 2: build the evidence bundle for a class pair."""
    anchor = _anchor_relation(
        a["iri"], b["iri"],
        a.get("parent_iris", []),
        b.get("parent_iris", []),
    )

    jac      = _jaccard(a["name"], b["name"])       if a["name"] and b["name"] else MISSING
    str_s    = _string_sim(a["name"], b["name"])    if a["name"] and b["name"] else MISSING
    name_sim = max(jac, str_s) if jac is not None and str_s is not None else (jac or str_s)

    alias_sim = _alias_best(a.get("aliases", []), b.get("aliases", []))

    # M3 — definition cosine; fall back to string_sim
    def_sim = _cosine(a.get("definition", ""), b.get("definition", ""))
    if def_sim is MISSING:
        da, db = a.get("definition", ""), b.get("definition", "")
        def_sim = _string_sim(da, db) if da and db else MISSING

    unit_compat = _unit_compatible(a.get("units", []), b.get("units", []))

    return SignalVector(
        name_similarity = name_sim,
        token_jaccard   = jac,
        alias_overlap   = alias_sim,
        def_similarity  = def_sim,
        unit_compatible = unit_compat,
        anchor_relation = anchor,
    )


# ---------------------------------------------------------------------------
# Stage 3 — Calibration
# ---------------------------------------------------------------------------

def calibrate(sv: SignalVector) -> tuple[float, str]:
    """
    Stage 3: combine signal vector → (confidence 0–1, regime).

    Anchored regime: IRI anchor determines confidence directly.
    Statistical regime: M1 fixed-weight average + definition blend + unit bonus.
    """
    # Anchored pathway
    if sv.anchor_relation == "identical":
        conf = 1.0 if (sv.unit_compatible is None or sv.unit_compatible) else 0.90
        return conf, "anchored"
    if sv.anchor_relation in ("broader", "narrower"):
        return BROAD_CONF, "anchored"
    if sv.anchor_relation == "unrelated":
        return 0.0, "anchored"

    # Statistical pathway — normalise over present signals only (Invariant 3)
    stats = [
        (W_NAME,    sv.name_similarity),
        (W_JACCARD, sv.token_jaccard),
        (W_ALIAS,   sv.alias_overlap),
    ]
    w_sum = sum(w for w, v in stats if v is not MISSING and w > 0)
    s_sum = sum(w * v for w, v in stats if v is not MISSING and w > 0)
    score = s_sum / w_sum if w_sum else 0.0

    # Blend in definition similarity (M3) — not in M1 weights but informative
    if sv.def_similarity is not MISSING:
        score = score * 0.75 + sv.def_similarity * 0.25

    if sv.unit_compatible is True:
        score = min(1.0, score + UNIT_BONUS)

    return round(score, 6), "statistical"


# ---------------------------------------------------------------------------
# Stage 4 — Predicate assignment
# ---------------------------------------------------------------------------

def assign_predicate(sv: SignalVector, confidence: float, regime: str) -> tuple[str, float] | None:
    """
    Stage 4: (sv, confidence, regime) → (skos_predicate, confidence) or None.

    Invariant 4: statistical evidence alone caps at skos:closeMatch.
    Only anchored evidence can yield skos:exactMatch.
    Returns None when the pair is below the confidence floor.
    """
    if regime == "anchored":
        rel = sv.anchor_relation
        if rel == "identical":
            if confidence >= EXACT_CONF and (sv.unit_compatible is None or sv.unit_compatible):
                return "skos:exactMatch", confidence
            return "skos:closeMatch", confidence   # unit mismatch → downgrade
        if rel == "broader":
            return "skos:broadMatch", confidence
        if rel == "narrower":
            return "skos:narrowMatch", confidence
        return None  # "unrelated"

    # Statistical — cap at closeMatch
    if confidence >= CLOSE_CONF:
        return "skos:closeMatch", confidence
    if confidence >= RELATED_FLOOR:
        return "skos:relatedMatch", confidence
    return None


# ---------------------------------------------------------------------------
# Stage 5 — Structural sanity repair
# ---------------------------------------------------------------------------

@dataclass
class _Pending:
    a:          dict
    b:          dict
    confidence: float
    predicate:  str
    sv:         SignalVector
    method:     str
    subscores:  dict


def repair_structural(pending: list[_Pending]) -> list[_Pending]:
    """
    Stage 5 M1: enforce one-to-one cardinality for exactMatch.

    If multiple exactMatch edges share the same subject, keep the highest-
    confidence one; demote the rest to closeMatch (demote-don't-delete).
    """
    best_exact: dict[str, tuple[float, int]] = {}
    for i, p in enumerate(pending):
        if p.predicate == "skos:exactMatch":
            prev = best_exact.get(p.a["hash_id"])
            if prev is None or p.confidence > prev[0]:
                best_exact[p.a["hash_id"]] = (p.confidence, i)

    repaired = []
    for i, p in enumerate(pending):
        if p.predicate == "skos:exactMatch":
            if best_exact.get(p.a["hash_id"], (None, i))[1] != i:
                from dataclasses import replace
                p = replace(p, predicate="skos:closeMatch")
        repaired.append(p)
    return repaired


# ---------------------------------------------------------------------------
# Combined pipeline entry point
# ---------------------------------------------------------------------------

def compute_alignment(a: dict, b: dict) -> _Pending | None:
    """
    Run stages 1-4 for a single pair.
    Returns a _Pending record or None if the pair should be dropped.
    Stage 1 unit veto is the caller's responsibility (handled in CLI loop).
    """
    sv                = compute_signals(a, b)
    confidence, regime = calibrate(sv)
    pred_result        = assign_predicate(sv, confidence, regime)
    if pred_result is None:
        return None
    predicate, confidence = pred_result
    distance = round(1.0 - confidence, 6)

    subscores = {
        "iri":    1.0 if sv.anchor_relation == "identical" else 0.0,
        "name":   sv.name_similarity or 0.0,
        "desc":   sv.def_similarity  or 0.0,
        "slot":   0.0,
        "jaccard":sv.token_jaccard   or 0.0,
    }
    if regime == "anchored":
        method = "anchored-iri"
    elif (sv.def_similarity or 0) > 0.75:
        method = "semantic-desc"
    elif (sv.name_similarity or 0) > 0.75:
        method = "semantic-name"
    else:
        method = "composite"

    return _Pending(a=a, b=b, confidence=confidence, predicate=predicate,
                    sv=sv, method=method, subscores=subscores)


# ---------------------------------------------------------------------------
# Stage 0 — Load classes from LadybugDB
# ---------------------------------------------------------------------------

def load_classes(conn, source_label: str | None = None) -> list[dict]:
    """
    Stage 0: build MatchingProfiles from RegistryClass nodes.
    Loads name, IRI, definition, parent IRIs, slot IRIs, and units.
    """
    if source_label:
        rows = conn.execute("""
            MATCH (n:RegistryClass)-[:HAS_PROVENANCE]->(:ProvenanceEntry {source: $src})
            RETURN DISTINCT n.hash_id, n.class_uri, n.name, n.description
        """, {"src": source_label}).get_all()
    else:
        rows = conn.execute("""
            MATCH (n:RegistryClass)
            RETURN n.hash_id, n.class_uri, n.name, n.description
        """).get_all()

    classes = []
    for hash_id, class_uri, name, desc in rows:
        sources = {
            r[0] for r in conn.execute("""
                MATCH (:RegistryClass {hash_id: $h})-[:HAS_PROVENANCE]->(pe:ProvenanceEntry)
                RETURN pe.source
            """, {"h": hash_id}).get_all()
        }
        if not sources:
            continue

        slot_iris = [
            r[0] for r in conn.execute("""
                MATCH (c:RegistryClass {hash_id: $h})-[:HAS_PROPERTY]->(p:RegistryProperty)
                RETURN p.slot_uri
            """, {"h": hash_id}).get_all() if r[0]
        ]
        units = [
            r[0] for r in conn.execute("""
                MATCH (c:RegistryClass {hash_id: $h})-[:HAS_PROPERTY]->(p:RegistryProperty)
                WHERE p.units IS NOT NULL
                RETURN p.units
            """, {"h": hash_id}).get_all() if r[0]
        ]
        parent_iris = [
            r[0] for r in conn.execute("""
                MATCH (c:RegistryClass {hash_id: $h})-[:SUBCLASS_OF]->(p:RegistryClass)
                RETURN p.class_uri
            """, {"h": hash_id}).get_all() if r[0]
        ]
        classes.append({
            "hash_id":    hash_id,
            "iri":        class_uri or "",
            "name":       name      or "",
            "definition": desc      or "",
            "sources":    sources,
            "slot_iris":  slot_iris,
            "parent_iris":parent_iris,
            "units":      units,
            "aliases":    [],  # M3 — populated when alias data lands in schema
        })
    return classes


# ---------------------------------------------------------------------------
# Stage 1 — Blocking: pairs across sources
# ---------------------------------------------------------------------------

def pairs_across_sources(
    classes: list[dict],
    source_a: str | None,
) -> Iterator[tuple[dict, dict]]:
    """
    Stage 1 blocking: generate recall-focused cross-source class pairs.
    A class attested by multiple sources can appear in multiple groups;
    `seen` deduplicates by hash_id pair so no pair is compared twice.
    """
    all_sources = {s for c in classes for s in c["sources"]}
    if len(all_sources) < 2:
        return

    seen: set[tuple[str, str]] = set()

    def _mark(a: dict, b: dict) -> bool:
        key = tuple(sorted((a["hash_id"], b["hash_id"])))
        if key in seen:
            return False
        seen.add(key)
        return True

    if source_a:
        group_a = [c for c in classes if source_a in c["sources"]]
        group_b = [c for c in classes if source_a not in c["sources"]]
        for a in group_a:
            for b in group_b:
                if _mark(a, b):
                    yield a, b
    else:
        by_source: dict[str, list] = {}
        for c in classes:
            for s in c["sources"]:
                by_source.setdefault(s, []).append(c)
        for s1, s2 in combinations(sorted(all_sources), 2):
            for a in by_source[s1]:
                for b in by_source[s2]:
                    if a["sources"] == b["sources"]:
                        continue
                    if _mark(a, b):
                        yield a, b


# ---------------------------------------------------------------------------
# Stage 6 — Write alignment to LadybugDB
# ---------------------------------------------------------------------------

def write_alignment(conn, p: _Pending, registry_version: str = "") -> None:
    """Stage 6: write an ALIGNED_TO edge. Deletes any stale edge first."""
    conn.execute("""
        MATCH (a:RegistryClass {hash_id: $ua})-[r:ALIGNED_TO]->(b:RegistryClass {hash_id: $ub})
        DELETE r
    """, {"ua": p.a["hash_id"], "ub": p.b["hash_id"]})

    conn.execute("""
        MATCH (a:RegistryClass {hash_id: $ua}), (b:RegistryClass {hash_id: $ub})
        CREATE (a)-[:ALIGNED_TO {
            distance:         $d,
            method:           $m,
            skos_relation:    $sr,
            score_iri:        $si,
            score_name:       $sn,
            score_desc:       $sd,
            score_slot:       $ss,
            registry_version: $rv
        }]->(b)
    """, {
        "ua": p.a["hash_id"],
        "ub": p.b["hash_id"],
        "d":  round(1.0 - p.confidence, 6),
        "m":  p.method,
        "sr": p.predicate,
        "si": p.subscores["iri"],
        "sn": p.subscores["name"],
        "sd": p.subscores["desc"],
        "ss": p.subscores["slot"],
        "rv": registry_version,
    })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--source",           default=None,
              help="Align this source against all others. Default: all pairs.")
@click.option("--db",               default=DB_PATH, show_default=True)
@click.option("--threshold",        default=0.85, show_default=True, type=float,
              help="Drop edges where distance > threshold (confidence < 1-threshold).")
@click.option("--registry-version", default="",
              help="Registry version stamped on ALIGNED_TO edges.")
@click.option("--dry-run",          is_flag=True,
              help="Print pairs without writing to graph.")
@click.option("--save-cache",       is_flag=True, default=True,
              help="Persist new embeddings to parquet cache.")
def cli(source, db, threshold, registry_version, dry_run, save_cache) -> None:
    """
    Compute Proteus-aligned semantic alignment between RegistryClass nodes.

    Runs stages 0-6: profile loading, blocking + unit veto, signal vectors,
    calibration, predicate assignment, structural repair, and ALIGNED_TO writes.

    Examples:
      python align.py --source bbqs --dry-run
      python align.py --threshold 0.5   # only close matches
    """
    global _cache_dirty

    conn    = get_connection(db)
    classes = load_classes(conn)

    if not classes:
        click.echo("No classes found. Run seed.py and ingest_linkml.py first.")
        return

    sources = {s for c in classes for s in c["sources"]}
    click.echo(
        f"Loaded {len(classes)} classes from {len(sources)} sources: "
        f"{', '.join(sorted(sources))}"
    )

    by_source: dict[str, list] = {}
    for c in classes:
        for s in c["sources"]:
            by_source.setdefault(s, []).append(c)
    click.echo("  IRI coverage per source:")
    for src, grp in sorted(by_source.items()):
        with_iri = [c for c in grp if c["iri"]]
        sample   = with_iri[0]["iri"] if with_iri else "—"
        click.echo(f"    {src}: {len(with_iri)}/{len(grp)} have IRIs  e.g. {sample}")

    _get_model()
    _embedding_cache.update(_load_embedding_cache())

    pending: list[_Pending] = []
    vetoed = 0

    for a, b in pairs_across_sources(classes, source):
        # Stage 1 hard veto (Invariant 1)
        if _unit_veto(a.get("units", []), b.get("units", [])):
            vetoed += 1
            continue

        result = compute_alignment(a, b)
        if result is None:
            continue

        if (1.0 - result.confidence) > threshold:
            continue

        pending.append(result)

    # Stage 5 — structural repair
    pending = repair_structural(pending)

    written = exact = close = broad = narrow = related = 0

    for p in pending:
        distance = round(1.0 - p.confidence, 6)

        if dry_run:
            a_src = ",".join(sorted(p.a["sources"]))
            b_src = ",".join(sorted(p.b["sources"]))
            click.echo(
                f"  [{p.predicate}] {a_src}:{p.a['name']} ↔ "
                f"{b_src}:{p.b['name']}  "
                f"d={distance:.4f} conf={p.confidence:.4f} "
                f"(name={p.subscores['name']:.2f} "
                f"jac={p.subscores['jaccard']:.2f} "
                f"desc={p.subscores['desc']:.2f})"
            )
        else:
            write_alignment(conn, p, registry_version)

        written += 1
        if p.predicate == "skos:exactMatch":    exact   += 1
        elif p.predicate == "skos:closeMatch":  close   += 1
        elif p.predicate == "skos:broadMatch":  broad   += 1
        elif p.predicate == "skos:narrowMatch": narrow  += 1
        elif p.predicate == "skos:relatedMatch":related += 1

    action = "Would write" if dry_run else "Wrote"
    click.echo(
        f"\n{action} {written} ALIGNED_TO edges "
        f"(exact={exact} close={close} broad={broad} narrow={narrow} related={related} "
        f"vetoed={vetoed})."
    )

    if save_cache and _cache_dirty and not dry_run:
        _save_embedding_cache(_embedding_cache)


if __name__ == "__main__":
    cli()
