"""
converters/dandi.py — Fetch DANDI schema and convert to LinkML
--------------------------------------------------------------
Source: https://github.com/dandi/dandi-schema
        dandischema/models.py (Pydantic models)
        also publishes dandischema/schema/*.json (JSON Schema)

DANDI already has a LinkML representation in progress.
We pull the JSON Schema version and convert.
"""

from __future__ import annotations
import httpx, yaml, json
from pathlib import Path

GITHUB_RAW  = "https://raw.githubusercontent.com/dandi/dandi-schema/master/dandischema/schema"
SCHEMA_FILE = "dandiset.json"
OUT_PATH    = Path("schemas/dandi.yml")

JSON_SCHEMA_TYPE_MAP = {
    "string":  "xsd:string",
    "number":  "xsd:float",
    "integer": "xsd:integer",
    "boolean": "xsd:boolean",
    "array":   "xsd:string",
    "object":  "xsd:string",
    "null":    "xsd:string",
}

DANDI_SCHEMA_ORG_MAP = {
    "identifier": "schema:identifier",
    "name":       "schema:name",
    "description":"schema:description",
    "url":        "schema:url",
    "license":    "schema:license",
    "citation":   "schema:citation",
    "keywords":   "schema:keywords",
    "version":    "schema:version",
    "datePublished": "schema:datePublished",
    "dateModified":  "schema:dateModified",
    "contributor":   "schema:contributor",
    "about":         "schema:about",
}


def fetch_json(url: str) -> dict:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def props_from_json_schema(name: str, schema: dict) -> tuple[dict, dict]:
    """Extract classes and slots from a JSON Schema definition."""
    classes: dict = {}
    slots:   dict = {}

    def process_def(def_name: str, def_body: dict) -> None:
        if def_body.get("type") == "object" or "properties" in def_body:
            slot_names = []
            for prop_name, prop_body in (def_body.get("properties") or {}).items():
                raw_type = prop_body.get("type", "string")
                if isinstance(raw_type, list):
                    raw_type = next((t for t in raw_type if t != "null"), "string")
                xsd  = JSON_SCHEMA_TYPE_MAP.get(raw_type, "xsd:string")
                key  = f"{def_name}__{prop_name}"
                slots[key] = {
                    "description": prop_body.get("description", ""),
                    "slot_uri":    DANDI_SCHEMA_ORG_MAP.get(
                        prop_name,
                        f"https://schema.dandiarchive.org/#{prop_name}"
                    ),
                    "range":       xsd.replace("xsd:", ""),
                    "multivalued": raw_type == "array",
                    "required":    prop_name in (def_body.get("required") or []),
                }
                slot_names.append(key)
            classes[def_name] = {
                "description": def_body.get("description", ""),
                "class_uri":   f"https://schema.dandiarchive.org/#{def_name}",
                "slots":       slot_names,
            }

    # Process $defs / definitions
    for def_name, def_body in (schema.get("$defs") or schema.get("definitions") or {}).items():
        process_def(def_name, def_body)

    # Process root object
    if schema.get("type") == "object" or "properties" in schema:
        process_def(name, schema)

    return classes, slots


def convert() -> dict:
    print("[dandi] Fetching DANDI schema…")
    all_classes: dict = {}
    all_slots:   dict = {}

    # Try main dandiset schema
    urls_to_try = [
        f"{GITHUB_RAW}/{SCHEMA_FILE}",
        "https://raw.githubusercontent.com/dandi/dandi-schema/master/dandischema/schema/dandiset.json",
        "https://raw.githubusercontent.com/dandi/dandi-schema/master/dandischema/schema.py",
    ]
    for url in urls_to_try:
        try:
            if url.endswith(".json"):
                data = fetch_json(url)
                cls, slt = props_from_json_schema("Dandiset", data)
                all_classes.update(cls)
                all_slots.update(slt)
                print(f"[dandi]   Loaded {url}: {len(cls)} classes")
                break
        except Exception as e:
            print(f"[dandi]   WARNING: {url} — {e}")

    # Always include core DANDI types manually as fallback
    if not all_classes:
        print("[dandi]   Using fallback core types")
        all_classes = {
            "Dandiset": {
                "description": "A collection of NWB files and metadata.",
                "class_uri": "https://schema.dandiarchive.org/#Dandiset",
                "slots": ["dandiset__identifier","dandiset__name","dandiset__description",
                          "dandiset__license","dandiset__version","dandiset__contributor",
                          "dandiset__keywords","dandiset__about"],
            },
            "Asset": {
                "description": "A single file or object within a Dandiset.",
                "class_uri": "https://schema.dandiarchive.org/#Asset",
                "slots": ["asset__identifier","asset__path","asset__size",
                          "asset__dateModified","asset__digest"],
            },
            "Participant": {
                "description": "A research subject / participant.",
                "class_uri": "schema:Person",
                "slots": ["participant__identifier","participant__age",
                          "participant__sex","participant__species"],
            },
        }
        all_slots = {
            "dandiset__identifier": {"description":"DANDI identifier","range":"string","slot_uri":"schema:identifier"},
            "dandiset__name": {"description":"Name of dandiset","range":"string","slot_uri":"schema:name"},
            "dandiset__description": {"description":"Description","range":"string","slot_uri":"schema:description"},
            "dandiset__license": {"description":"License","range":"string","slot_uri":"schema:license"},
            "dandiset__version": {"description":"Version","range":"string","slot_uri":"schema:version"},
            "dandiset__contributor": {"description":"Contributors","range":"string","slot_uri":"schema:contributor","multivalued":True},
            "dandiset__keywords": {"description":"Keywords","range":"string","slot_uri":"schema:keywords","multivalued":True},
            "dandiset__about": {"description":"Species / anatomy studied","range":"string","slot_uri":"schema:about","multivalued":True},
            "asset__identifier": {"description":"Asset identifier","range":"string","slot_uri":"schema:identifier"},
            "asset__path": {"description":"File path","range":"string"},
            "asset__size": {"description":"File size bytes","range":"integer"},
            "asset__dateModified": {"description":"Date modified","range":"date","slot_uri":"schema:dateModified"},
            "asset__digest": {"description":"Content hash","range":"string"},
            "participant__identifier": {"description":"Subject identifier","range":"string","slot_uri":"schema:identifier"},
            "participant__age": {"description":"Subject age (ISO 8601 duration or BirthReference)","range":"string"},
            "participant__sex": {"description":"Biological sex","range":"string"},
            "participant__species": {"description":"Species","range":"string"},
        }

    return {
        "id":      "https://schema.dandiarchive.org/",
        "name":    "dandi",
        "title":   "DANDI Schema",
        "description": "DANDI Archive schema for neurophysiology datasets.",
        "license": "CC-BY-4.0",
        "version": "0.6.4",
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
    print(f"[dandi] Wrote {out_path} "
          f"({len(schema['classes'])} classes, {len(schema['slots'])} slots)")


if __name__ == "__main__":
    run()
