"""
converters/bids.py — Fetch BIDS schema and convert to LinkML
-------------------------------------------------------------
Source: https://github.com/bids-standard/bids-specification
        src/schema/objects/  (YAML files per object type)

BIDS schema is split into multiple YAML files:
  objects/columns.yaml    → data dictionary columns (→ SchemaProperty)
  objects/entities.yaml   → entities like sub, ses, task (→ SchemaProperty)
  objects/datatypes.yaml  → imaging datatypes (→ SchemaClass)
  objects/suffixes.yaml   → file suffixes (→ SchemaClass)
  objects/metadata.yaml   → sidecar metadata fields (→ SchemaProperty)
"""

from __future__ import annotations
import httpx, yaml
from pathlib import Path

GITHUB_RAW = "https://raw.githubusercontent.com/bids-standard/bids-specification/master/src/schema/objects"
OUT_PATH   = Path("schemas/bids.yml")

FILES = {
    "columns":  f"{GITHUB_RAW}/columns.yaml",
    "entities": f"{GITHUB_RAW}/entities.yaml",
    "metadata": f"{GITHUB_RAW}/metadata.yaml",
}

XSD_TYPE_MAP = {
    "number":  "xsd:float",
    "integer": "xsd:integer",
    "string":  "xsd:string",
    "boolean": "xsd:boolean",
    "array":   "xsd:string",
    "object":  "xsd:string",
}


def fetch(url: str) -> dict:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return yaml.safe_load(resp.text)


def convert() -> dict:
    print("[bids] Fetching schema…")
    classes: dict  = {}
    slots:   dict  = {}

    # Metadata fields → properties
    try:
        meta = fetch(FILES["metadata"])
        for name, defn in (meta or {}).items():
            if not isinstance(defn, dict):
                continue
            raw_type = defn.get("type", "string")
            if isinstance(raw_type, list):
                raw_type = raw_type[0]
            xsd = XSD_TYPE_MAP.get(raw_type, "xsd:string")
            slots[name] = {
                "description": defn.get("description", ""),
                "slot_uri":    f"https://bids-specification.readthedocs.io/en/stable/glossary.html#{name}",
                "range":       xsd.replace("xsd:", ""),
                "multivalued": raw_type == "array",
            }
        print(f"[bids]   {len(slots)} metadata slots")
    except Exception as e:
        print(f"[bids]   WARNING: metadata fetch failed — {e}")

    # Columns → properties
    try:
        cols = fetch(FILES["columns"])
        for name, defn in (cols or {}).items():
            if not isinstance(defn, dict) or name in slots:
                continue
            raw_type = defn.get("type", "string")
            if isinstance(raw_type, list):
                raw_type = raw_type[0]
            xsd = XSD_TYPE_MAP.get(raw_type, "xsd:string")
            slots[name] = {
                "description": defn.get("description", ""),
                "slot_uri":    f"https://bids-specification.readthedocs.io/en/stable/glossary.html#{name}",
                "range":       xsd.replace("xsd:", ""),
                "multivalued": False,
            }
        print(f"[bids]   {len(slots)} total slots after columns")
    except Exception as e:
        print(f"[bids]   WARNING: columns fetch failed — {e}")

    # Top-level BIDSDataset class that owns all slots
    classes["BIDSDataset"] = {
        "description": "A BIDS-compliant dataset.",
        "class_uri":   "https://bids-specification.readthedocs.io/en/stable/",
        "slots":       list(slots.keys())[:60],  # cap for manageability
    }

    return {
        "id":      "https://bids-specification.readthedocs.io/en/stable/",
        "name":    "bids",
        "title":   "BIDS Schema",
        "description": "Brain Imaging Data Structure (BIDS) specification schema.",
        "license": "CC0-1.0",
        "version": "1.9.0",
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "schema": "https://schema.org/",
            "bids":   "https://bids-specification.readthedocs.io/en/stable/",
            "xsd":    "http://www.w3.org/2001/XMLSchema#",
        },
        "default_prefix": "bids",
        "default_range":  "string",
        "imports": ["linkml:types"],
        "classes": classes,
        "slots":   slots,
    }


def run(out_path: Path = OUT_PATH) -> None:
    schema = convert()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.dump(schema, f, default_flow_style=False, allow_unicode=True)
    print(f"[bids] Wrote {out_path} "
          f"({len(schema['classes'])} classes, {len(schema['slots'])} slots)")


if __name__ == "__main__":
    run()
