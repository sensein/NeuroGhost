"""
converters/from_jsonschema.py — Convert JSON Schema to LinkML YAML
------------------------------------------------------------------
Used by the schema-submission workflow when a contributor submits their
schema as JSON Schema (```json or ```json-schema fence) instead of LinkML,
and as the back-end for Pydantic ingestion (Pydantic emits JSON Schema via
`Model.model_json_schema()`, which is fed straight through here).

The heavy lifting is done by the LinkML ecosystem's own JSON Schema importer
(`schema_automator.importers.JsonSchemaImportEngine`), rather than a
hand-rolled walk — it resolves `$ref` to real class-typed ranges, handles
arrays and `required`, and inline `enum`s.

The importer has gaps, each worked around by its own small `_patch_*`
function so they can be removed independently as the matching upstream fixes
land (see NOTES / upstream-PR tracking):
  * `_patch_slot_constraints` — recovers `pattern` (importer drops it) and
    `minimum`/`maximum` (importer bug reads LinkML key names off a JSON dict).
    Feeds the RegistryRule PATTERN / MIN_VALUE / MAX_VALUE builders.
  * `_patch_format_ranges` — maps string `format` to the equivalent LinkML
    type range (uri/date-time/date/time); formats with no LinkML type
    (email/uuid/...) stay strings and are warned about.
  * `_patch_string_length` — encodes `minLength`/`maxLength` (no native LinkML
    facet) as a length `pattern`, unless the field has a real pattern.
  * `_patch_anyof_ranges` — fills a slot's LinkML `any_of` from an `anyOf`
    union of $refs/scalars (importer can't translate it); parse_linkml reads
    it into the multivalued range, landing as several RANGE RegistryRules.
  * `_patch_enum_definitions` — a top-level definition that IS an enum (the
    reusable `$ref`-ed idiom, e.g. dandi's RoleType) is turned into an empty
    class by the importer; re-emitted as a real LinkML enum.

`_apply_registry_conventions` is separate (not an importer workaround): it
overrides the importer's title-derived schema name/id with the registry's
submission name + IRI so provenance/dedup key on a stable label.

Not covered: type-less string formats (email/uuid/ipv4/...) — no LinkML type,
so they stay plain strings (warned). A FORMAT RegistryRule would preserve the
format name, but that builder isn't wired up yet.

Usage (CLI):
    python -m neuro_ghost.converters.from_jsonschema input.json output.yml
    python -m neuro_ghost.converters.from_jsonschema input.json  # prints to stdout

Usage (library):
    from neuro_ghost.converters.from_jsonschema import convert
    linkml_dict = convert(json_schema_dict, name="my-schema")
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml
from schema_automator.importers.jsonschema_import_engine import (
    JsonSchemaImportEngine, RESERVED,
)
from linkml_runtime.linkml_model import EnumDefinition, PermissibleValue
from linkml_runtime.linkml_model.meta import AnonymousSlotExpression
from linkml_runtime.utils.schema_as_dict import schema_as_dict

REG = "https://registry.sensein.io"

# JSON Schema primitive type -> LinkML type name (for anyOf scalar members).
_JSON_PRIMITIVE = {
    "string": "string", "integer": "integer",
    "number": "float", "boolean": "boolean",
}


def _slot_name(prop_name: str) -> str:
    """Mirror the importer's reserved-name mangling (`in` -> `_in`) so the
    patch passes look up the same slot key the importer created."""
    return f"_{prop_name}" if prop_name in RESERVED else prop_name


def _properties_blocks(data: dict) -> Iterator[dict]:
    """Every JSON Schema `properties` block: the root object plus each entry
    under `$defs` (draft 2019-09+) / `definitions` (draft-07)."""
    if isinstance(data.get("properties"), dict):
        yield data["properties"]
    for section in ("$defs", "definitions"):
        for d in (data.get(section) or {}).values():
            if isinstance(d, dict) and isinstance(d.get("properties"), dict):
                yield d["properties"]


# ===========================================================================
# Importer-gap patches
# ===========================================================================
# Each function below works around one specific thing schema-automator's
# JsonSchemaImportEngine gets wrong or drops. They are deliberately separate,
# one gap per function, so each can be deleted independently once the
# corresponding upstream fix lands and the schema-automator pin is bumped —
# without disturbing the others. See NOTES / the upstream-PR tracking.

def _patch_slot_constraints(sd, data: dict) -> None:
    """GAP: the importer drops `pattern` (unsupported) and `minimum`/`maximum`
    (bug: it reads LinkML key names `minimum_value`/`maximum_value` off a JSON
    Schema dict, always None). Re-apply them onto the global slot defs by
    property name, so they survive SchemaView induction into parse_linkml()
    and reach the RegistryRule builders (PATTERN / MIN_VALUE / MAX_VALUE).

    REMOVE once schema-automator supports `pattern` and fixes the min/max
    key bug upstream."""
    for block in _properties_blocks(data):
        for pname, pschema in block.items():
            if not isinstance(pschema, dict):
                continue
            slot = sd.slots.get(_slot_name(pname))
            if slot is None:
                continue
            if "pattern" in pschema:
                slot.pattern = pschema["pattern"]
            if "minimum" in pschema:
                slot.minimum_value = pschema["minimum"]
            if "maximum" in pschema:
                slot.maximum_value = pschema["maximum"]


# JSON Schema string `format` -> the LinkML type that means the same thing.
# Only formats with a real LinkML/XSD type equivalent; the rest (email, uuid,
# ipv4, hostname, ...) have no LinkML type and stay plain strings (warned).
_FORMAT_TO_LINKML_TYPE = {
    "uri": "uri", "uri-reference": "uri", "iri": "uri", "url": "uri",
    "date-time": "datetime", "date": "date", "time": "time",
}


def _patch_format_ranges(sd, data: dict) -> None:
    """GAP: the importer drops JSON Schema string `format` entirely, so a
    `{type: string, format: uri}` becomes a plain string, losing the datatype
    distinction align.py's compatibility check reads off the property's RANGE
    rule.

    Where a LinkML type means the same thing (uri/date-time/date/time), set
    the slot's range to it — the idiomatic LinkML encoding, cleaner than a
    rule. Formats with no LinkML type (email, uuid, ipv4, ...) can't be
    represented natively; they stay strings and are reported via a warning
    (a FORMAT RegistryRule would capture them — not built yet).

    REMOVE the mapped part if schema-automator maps format->type upstream."""
    unmapped: set[str] = set()
    for block in _properties_blocks(data):
        for pname, pschema in block.items():
            if not isinstance(pschema, dict):
                continue
            fmt = pschema.get("format")
            if not fmt or pschema.get("type") != "string":
                continue
            slot = sd.slots.get(_slot_name(pname))
            if slot is None:
                continue
            linkml_type = _FORMAT_TO_LINKML_TYPE.get(fmt)
            if linkml_type:
                slot.range = linkml_type
            else:
                unmapped.add(fmt)

    if unmapped:
        print(
            "WARNING: from_jsonschema: JSON Schema format(s) with no LinkML "
            f"type kept as plain string (format detail lost): "
            f"{', '.join(sorted(unmapped))}. "
            "A FORMAT rule would preserve these, but that isn't wired up yet.",
            file=sys.stderr,
        )


def _patch_string_length(sd, data: dict) -> None:
    """GAP: JSON Schema `minLength`/`maxLength` (string-length bounds) have no
    native LinkML facet at all — LinkML's minimum_value/maximum_value are
    numeric, and there is no min_length/max_length metaslot. So encode the
    bound as a length `pattern` (`^[\\s\\S]{lo,hi}$`, [\\s\\S] to count every
    character incl. newlines), which parse_linkml -> RegistryRule turns into a
    PATTERN rule.

    Only applied when the field has no `pattern` of its own — a real pattern
    is the more specific constraint and must not be clobbered. Run after
    _patch_slot_constraints so any recovered pattern is already in place.

    REMOVE (or switch to a real length facet) if LinkML gains native
    min_length/max_length — worth suggesting upstream."""
    for block in _properties_blocks(data):
        for pname, pschema in block.items():
            if not isinstance(pschema, dict):
                continue
            lo, hi = pschema.get("minLength"), pschema.get("maxLength")
            if lo is None and hi is None:
                continue
            if "pattern" in pschema:            # respect the source's own pattern
                continue
            slot = sd.slots.get(_slot_name(pname))
            if slot is None or slot.pattern:    # don't clobber an existing pattern
                continue
            quant = f"{{{lo or 0},}}" if hi is None else f"{{{lo or 0},{hi}}}"
            slot.pattern = rf"^[\s\S]{quant}$"


def _anyof_member_ranges(engine, anyof: list) -> list:
    """Map an `anyOf` member list to LinkML range names: a `$ref` -> the
    referenced class/enum name; a scalar `{type: ...}` -> its LinkML type.
    `null` members (Pydantic's `Optional[...]` wrapping) and bare `{}` are
    skipped — they carry no range."""
    ranges = []
    for m in anyof:
        if not isinstance(m, dict):
            continue
        if "$ref" in m:
            ranges.append(engine._class_name(m["$ref"].rsplit("/", 1)[-1]))
        elif m.get("type") in _JSON_PRIMITIVE:
            ranges.append(_JSON_PRIMITIVE[m["type"]])
    # de-dup, preserve order
    seen, out = set(), []
    for r in ranges:
        if r not in seen:
            seen.add(r); out.append(r)
    return out


def _patch_anyof_ranges(engine, sd, data: dict) -> None:
    """GAP: the importer can't translate an `anyOf` union range — a
    polymorphic property like `contributor: Person|Organization|Software`
    (dandi writes these as `{type: array, items: {anyOf: [$ref, ...]}}`) comes
    out with no range at all. Fill the slot's LinkML `any_of` from the union
    members so a multi-target range survives into parse_linkml -> the
    property's multivalued range -> several RANGE RegistryRules. `range`
    (single) is left unset, mirroring LinkML: a union lives in `any_of`.

    REMOVE once schema-automator translates anyOf unions upstream."""
    for block in _properties_blocks(data):
        for pname, pschema in block.items():
            if not isinstance(pschema, dict):
                continue
            # anyOf may sit directly on the property, or under array `items`.
            anyof = pschema.get("anyOf")
            if anyof is None and isinstance(pschema.get("items"), dict):
                anyof = pschema["items"].get("anyOf")
            if not isinstance(anyof, list):
                continue
            member_ranges = _anyof_member_ranges(engine, anyof)
            if len(member_ranges) < 2:      # 0/1 real members -> not a union
                continue
            slot = sd.slots.get(_slot_name(pname))
            if slot is None:
                continue
            slot.range = None
            slot.any_of = [AnonymousSlotExpression(range=r) for r in member_ranges]


def _patch_enum_definitions(engine, sd, data: dict) -> None:
    """GAP: the importer only turns an *inline* `{type: string, enum: [...]}`
    on a property into a LinkML enum. A top-level definition that IS an enum
    (the reusable, `$ref`-ed idiom — dandi's RoleType/LicenseType/...) becomes
    an empty class instead, losing every permissible value.

    Re-emit each such definition as a real LinkML EnumDefinition and drop the
    empty class the importer created. Slots that `$ref` the enum already carry
    range=<EnumName> (the importer set it), which LinkML resolves to the enum
    once it exists — so no slot rewrites are needed here.

    REMOVE once schema-automator handles top-level enum definitions upstream."""
    for section in ("$defs", "definitions"):
        for name, jdef in (data.get(section) or {}).items():
            if not (isinstance(jdef, dict) and isinstance(jdef.get("enum"), list)):
                continue
            enum_name = engine._class_name(name)
            ed = EnumDefinition(
                name=enum_name,
                description=(jdef.get("description") or "").strip() or None,
            )
            for value in jdef["enum"]:
                ed.permissible_values[str(value)] = PermissibleValue(text=str(value))
            sd.enums[enum_name] = ed
            sd.classes.pop(enum_name, None)  # drop the empty class the importer made


def _apply_registry_conventions(engine, sd, data: dict, name: str) -> None:
    """Override the importer's title-derived schema identity with the
    registry's submission name + IRI, and backfill the root-object
    description the importer drops onto the root class."""
    sd.name = name
    sd.id = f"{REG}/schema/{name}"
    if data.get("description"):
        sd.description = data["description"].strip()
    if not sd.version:
        sd.version = "1.0.0"
    if "linkml:types" not in (sd.imports or []):
        sd.imports = list(sd.imports or []) + ["linkml:types"]
    sd.default_range = sd.default_range or "string"

    # Root-object description -> root class (importer keeps only slot descs).
    root = data.get("name") or data.get("title") or name
    root_cls = sd.classes.get(engine._class_name(root))
    if root_cls is not None and not root_cls.description and data.get("description"):
        root_cls.description = data["description"].strip()


def convert(data: dict, name: str) -> dict:
    """
    Convert a parsed JSON Schema dict to a LinkML schema dict.

    Parameters
    ----------
    data : dict
        Parsed JSON Schema (from json.loads or yaml.safe_load).
    name : str
        Schema name, used as the LinkML `name` field and in the ID IRI.

    Returns
    -------
    dict
        A LinkML-compatible dict ready to be YAML-serialised.

    Raises
    ------
    ValueError
        If the schema yields no classes.
    """
    engine = JsonSchemaImportEngine()
    sd = engine.loads(data, name=name)
    # Importer-gap patches — each independently removable (see their docstrings).
    _patch_slot_constraints(sd, data)
    _patch_format_ranges(sd, data)
    _patch_string_length(sd, data)   # after _patch_slot_constraints (checks pattern)
    _patch_anyof_ranges(engine, sd, data)
    _patch_enum_definitions(engine, sd, data)
    _apply_registry_conventions(engine, sd, data, name)

    if not sd.classes and not sd.enums:
        raise ValueError(
            "No object or enum definitions found in JSON Schema. "
            "The schema must have at least one object type with 'properties', "
            "or an enum definition."
        )

    return schema_as_dict(sd)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m neuro_ghost.converters.from_jsonschema "
              "<input.json> [output.yml]")
        sys.exit(1)

    in_path  = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    raw = in_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = yaml.safe_load(raw)

    name = in_path.stem
    result = convert(data, name)
    output = yaml.dump(result, default_flow_style=False, allow_unicode=True,
                       sort_keys=False)

    if out_path:
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote {out_path}  "
              f"({len(result.get('classes', {}))} classes, "
              f"{len(result.get('slots', {}))} slots)")
    else:
        print(output)


if __name__ == "__main__":
    main()
