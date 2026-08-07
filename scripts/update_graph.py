#!/usr/bin/env python3
"""
scripts/update_graph.py
-----------------------
Parse schemas/meta_model.yaml and regenerate the GN / GR constants in
index.html so the "Graph Schema" view always reflects the current meta model.

Run locally:  python scripts/update_graph.py
Called by CI: .github/workflows/update_graph.yml (on push that touches
              schemas/meta_model.yaml)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

ROOT       = Path(__file__).parent.parent
META_MODEL = ROOT / "schemas" / "meta_model.yaml"
INDEX_HTML = ROOT / "index.html"

# Classes whose slots are "rolled up" into their concrete children for display.
# Kept hidden in the graph because they're abstract and add visual noise.
ABSTRACT_BASES = {"RegistryEntity"}

# Edge labels for well-known slot names
_EDGE_LABELS: dict[str, str] = {
    "provenance":    "HAS_PROVENANCE",
    "skos_mappings": "HAS_SKOS_MAPPING",
    "properties":    "HAS_PROPERTY",
    "relations":     "HAS_RELATION",
    "is_a":          "SUBCLASS_OF",
    "mixins":        "MIXES_IN",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_slots(cdef: dict) -> list[str]:
    """Slot names declared directly on this class (not inherited)."""
    return list(cdef.get("slots") or []) + list((cdef.get("attributes") or {}).keys())


def _all_slots(cname: str, classes: dict) -> list[str]:
    """Own slots plus those inherited from any abstract base."""
    cdef = classes[cname]
    isa  = cdef.get("is_a")
    base = _own_slots(classes[isa]) if isa and isa in ABSTRACT_BASES and isa in classes else []
    return base + _own_slots(cdef)


def _slot_label(sname: str, sdef: dict) -> str:
    if sdef.get("identifier"):
        return f"{sname} PK"
    rng = sdef.get("range", "string")
    if rng and rng[0].isupper():           # FK / object reference
        mv = "[]" if sdef.get("multivalued") else ""
        return f"{sname} → {rng}{mv}"
    req = "*" if sdef.get("required") else ""
    return f"{sname}{req}"


# ---------------------------------------------------------------------------
# Core build
# ---------------------------------------------------------------------------

def build(mm: dict) -> tuple[list[dict], list[dict]]:
    classes   = mm.get("classes", {}) or {}
    slot_defs = mm.get("slots",   {}) or {}

    # db_inline classes (e.g. UnitOfMeasure) flatten onto their referencing
    # class's own node — matching db.py's _build_registry_ddl(), which never
    # gives them their own table or a real edge. No node, no edge for these.
    inline_classes = {
        name for name, cdef in classes.items()
        if cdef.get("annotations", {}).get("db_inline")
    }

    def _field_labels(cname: str) -> list[str]:
        labels = []
        for s in _all_slots(cname, classes):
            sdef = slot_defs.get(s, {})
            rng  = sdef.get("range", "")
            if rng in inline_classes:
                labels.extend(
                    _slot_label(sub_s, slot_defs.get(sub_s, {}))
                    for sub_s in _own_slots(classes[rng])
                )
            else:
                labels.append(_slot_label(s, sdef))
        return labels

    # --- Nodes ---------------------------------------------------------------
    nodes: list[dict] = []
    for cname, cdef in classes.items():
        if cdef.get("abstract") or cname in ABSTRACT_BASES or cname in inline_classes:
            continue
        fields = _field_labels(cname)
        is_stub = (cdef.get("description") or "").lstrip().startswith("STUB")
        nodes.append({
            "id":     cname,
            "fields": fields,
            "is_a":   cdef.get("is_a"),
            "_stub":  is_stub,
        })

    # --- Layout --------------------------------------------------------------
    # Tier 0: concrete classes that inherit from an abstract base (core entities)
    # Tier 1: standalone classes (ProvenanceEntry, Mapping, ValueSet …)
    # Tier 2: stubs (Rule, Transform)
    def _tier(n: dict) -> int:
        if n["_stub"]:
            return 2
        return 0 if (n["is_a"] and n["is_a"] in ABSTRACT_BASES) else 1

    groups: dict[int, list] = {}
    for n in nodes:
        groups.setdefault(_tier(n), []).append(n)

    for t, grp in sorted(groups.items()):
        cnt = len(grp)
        for i, n in enumerate(grp):
            n["x"] = round((i + 1) / (cnt + 1), 2)
            n["y"] = round(0.10 + t * 0.38, 2)

    # --- Edges ---------------------------------------------------------------
    visible = {n["id"] for n in nodes}
    edges: list[dict] = []
    seen:  set[tuple]  = set()

    for cname, cdef in classes.items():
        if cname not in visible:
            continue
        for sname in _all_slots(cname, classes):
            sdef = slot_defs.get(sname, {})
            rng  = sdef.get("range", "")
            if rng not in visible:
                continue
            label = _EDGE_LABELS.get(sname, f"HAS_{sname.upper()}")
            key   = (cname, rng, label)
            if key not in seen:
                edges.append({"f": cname, "t": rng, "l": label})
                seen.add(key)

    return nodes, edges


# ---------------------------------------------------------------------------
# Serialise to JS and patch index.html
# ---------------------------------------------------------------------------

def _to_js(nodes: list[dict], edges: list[dict]) -> tuple[str, str]:
    gn_lines = ["const GN=["]
    for n in nodes:
        gn_lines.append(
            f'  {{id:"{n["id"]}",fields:{json.dumps(n["fields"])},x:{n["x"]},y:{n["y"]}}},'
        )
    gn_lines.append("];")

    gr_lines = ["const GR=["]
    for e in edges:
        gr_lines.append(f'  {{f:"{e["f"]}",t:"{e["t"]}",l:"{e["l"]}"}},')
    gr_lines.append("];")

    return "\n".join(gn_lines), "\n".join(gr_lines)


def patch_html(gn_js: str, gr_js: str) -> None:
    html = INDEX_HTML.read_text()
    # Use lambda so re.sub doesn't interpret backslashes in the replacement string
    html = re.sub(r"const GN=\[.*?\];", lambda _: gn_js, html, flags=re.DOTALL)
    html = re.sub(r"const GR=\[.*?\];", lambda _: gr_js, html, flags=re.DOTALL)
    INDEX_HTML.write_text(html)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mm = yaml.safe_load(META_MODEL.read_text())
    nodes, edges = build(mm)
    gn_js, gr_js = _to_js(nodes, edges)
    patch_html(gn_js, gr_js)

    print(f"Updated index.html — {len(nodes)} nodes, {len(edges)} edges")
    for n in nodes:
        stub = " [stub]" if n["_stub"] else ""
        print(f"  node  {n['id']}{stub}  ({len(n['fields'])} fields)  pos=({n['x']}, {n['y']})")
    for e in edges:
        print(f"  edge  {e['f']} --{e['l']}--> {e['t']}")


if __name__ == "__main__":
    main()
