"""
converters/dandi.py — Fetch DANDI schema and convert to LinkML
--------------------------------------------------------------
The DANDI JSON schemas live in a SEPARATE repo from the Pydantic models:
  https://github.com/dandi/schema  (read-only, auto-generated)
  Path: releases/{version}/dandiset.json

The dandi/dandi-schema repo holds the Pydantic source code;
the dandi/schema repo holds the generated JSON Schema files.
"""

from __future__ import annotations
import httpx, yaml, json
from pathlib import Path

# Correct repo: dandi/schema, not dandi/dandi-schema
DANDI_SCHEMA_BASE = "https://raw.githubusercontent.com/dandi/schema/master/releases"
DANDI_VERSION     = "0.6.8"
OUT_PATH          = Path("schemas/dandi.yml")

JSON_SCHEMA_TYPE_MAP = {
    "string":  "xsd:string",
    "number":  "xsd:float",
    "integer": "xsd:integer",
    "boolean": "xsd:boolean",
    "array":   "xsd:string",
    "object":  "xsd:string",
}

SLOT_URI_MAP = {
    "identifier":    "schema:identifier",
    "name":          "schema:name",
    "description":   "schema:description",
    "url":           "schema:url",
    "license":       "schema:license",
    "version":       "schema:version",
    "datePublished": "schema:datePublished",
    "dateModified":  "schema:dateModified",
    "contributor":   "schema:contributor",
    "about":         "schema:about",
    "keywords":      "schema:keywords",
    "citation":      "schema:citation",
}


def fetch_json(url: str) -> dict:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def props_from_schema(name: str, schema: dict) -> tuple[dict, dict]:
    classes: dict = {}
    slots:   dict = {}

    def process(def_name: str, body: dict) -> None:
        if not isinstance(body, dict):
            return
        props = body.get("properties", {})
        if not props:
            return
        req = set(body.get("required") or [])
        slot_names = []
        for prop, pbody in props.items():
            if not isinstance(pbody, dict):
                continue
            raw_type = pbody.get("type", "string")
            if isinstance(raw_type, list):
                raw_type = next((t for t in raw_type if t != "null"), "string")
            xsd = JSON_SCHEMA_TYPE_MAP.get(raw_type, "xsd:string")
            key = f"{def_name}__{prop}"
            slots[key] = {
                "description": pbody.get("description", pbody.get("title", "")),
                "slot_uri":    SLOT_URI_MAP.get(prop, f"https://schema.dandiarchive.org/#{prop}"),
                "range":       xsd.replace("xsd:", ""),
                "multivalued": raw_type == "array",
                "required":    prop in req,
            }
            slot_names.append(key)
        classes[def_name] = {
            "description": body.get("description", body.get("title", f"DANDI {def_name}")),
            "class_uri":   f"https://schema.dandiarchive.org/#{def_name}",
            "slots":       slot_names,
        }
        # Recurse into $defs
        for d_name, d_body in (body.get("$defs") or body.get("definitions") or {}).items():
            process(d_name, d_body)

    process(name, schema)
    return classes, slots


def convert() -> dict:
    print("[dandi] Fetching DANDI schema from dandi/schema repo…")
    all_classes: dict = {}
    all_slots:   dict = {}

    # Try multiple version paths
    for ver in [DANDI_VERSION, "0.6.4", "0.6.0"]:
        for fname in ["dandiset.json", "asset.json"]:
            url = f"{DANDI_SCHEMA_BASE}/{ver}/{fname}"
            try:
                data = fetch_json(url)
                name = fname.replace(".json", "").capitalize()
                cls, slt = props_from_schema(name, data)
                all_classes.update(cls)
                all_slots.update(slt)
                print(f"[dandi]   {url} → {len(cls)} classes")
                break
            except Exception as e:
                print(f"[dandi]   WARNING: {url} — {e}")

    if not all_classes:
        print("[dandi]   Using fallback core types")
        all_classes = {
            "Dandiset": {
                "description": "A DANDI-archived collection of neurophysiology data.",
                "class_uri": "https://schema.dandiarchive.org/#Dandiset",
                "slots": ["dandiset__identifier","dandiset__name","dandiset__description",
                          "dandiset__license","dandiset__version","dandiset__contributor",
                          "dandiset__keywords","dandiset__about"],
            },
            "Asset": {
                "description": "A single file within a Dandiset.",
                "class_uri": "https://schema.dandiarchive.org/#Asset",
                "slots": ["asset__identifier","asset__path","asset__size","asset__dateModified"],
            },
            "Participant": {
                "description": "A research subject in a DANDI dataset.",
                "class_uri": "schema:Person",
                "slots": ["participant__identifier","participant__age",
                          "participant__sex","participant__species"],
            },
        }
        all_slots = {
            "dandiset__identifier": {"description":"DANDI ID","range":"string","slot_uri":"schema:identifier"},
            "dandiset__name": {"description":"Name","range":"string","slot_uri":"schema:name"},
            "dandiset__description": {"description":"Description","range":"string","slot_uri":"schema:description"},
            "dandiset__license": {"description":"License","range":"string","slot_uri":"schema:license"},
            "dandiset__version": {"description":"Version","range":"string","slot_uri":"schema:version"},
            "dandiset__contributor": {"description":"Contributors","range":"string","slot_uri":"schema:contributor","multivalued":True},
            "dandiset__keywords": {"description":"Keywords","range":"string","slot_uri":"schema:keywords","multivalued":True},
            "dandiset__about": {"description":"Species / anatomy","range":"string","slot_uri":"schema:about","multivalued":True},
            "asset__identifier": {"description":"Asset ID","range":"string","slot_uri":"schema:identifier"},
            "asset__path": {"description":"File path","range":"string"},
            "asset__size": {"description":"File size in bytes","range":"integer"},
            "asset__dateModified": {"description":"Date modified","range":"date","slot_uri":"schema:dateModified"},
            "participant__identifier": {"description":"Subject ID","range":"string","slot_uri":"schema:identifier"},
            "participant__age": {"description":"Age (ISO 8601 duration or BirthReference)","range":"string"},
            "participant__sex": {"description":"Biological sex","range":"string"},
            "participant__species": {"description":"Species","range":"string"},
        }

    return {
        "id":      "https://schema.dandiarchive.org/",
        "name":    "dandi",
        "title":   "DANDI Schema",
        "description": "DANDI Archive metadata schema for neurophysiology datasets.",
        "license": "CC-BY-4.0",
        "version": DANDI_VERSION,
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "schema": "https://schema.org/",
            "dandi":  "https://schema.dandiarchive.org/",
            "xsd":    "http://www.w3.org/2001/XMLSchema#",
        },
        "default_prefix": "dandi",
        "default_range":  "string",
        "imports": ["linkml:types"],
        "classes": all_classes,
        "slots":   all_slots,
    }


def run(out_path: Path = OUT_PATH) -> None:
    schema = convert()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.dump(schema, f, default_flow_style=False, allow_unicode=True)
    print(f"[dandi] Wrote {out_path} ({len(schema['classes'])} classes, {len(schema['slots'])} slots)")


if __name__ == "__main__":
    run()
