import hashlib
import json

from schema_registry_utils.models import RegistryClass, RegistryProperty

HASH_SUBSET = "HashSubset"


def _identity_fields(model_cls: type) -> set[str]:
    """
    The identity-defining fields of a RegistryEntity subclass — everything
    tagged `in_subset: [HashSubset]` in schemas/meta_model.yaml.

    The schema is the single source of truth for what's identity-defining,
    not a hand-maintained Python allowlist/denylist that could drift out of
    sync with it. gen-pydantic carries in_subset into each field's generated
    json_schema_extra['linkml_meta'], so this is a pure introspection of the
    already-generated model — no live SchemaView/YAML load needed here.
    """
    identity = set()
    for name, field in model_cls.model_fields.items():
        linkml_meta = (field.json_schema_extra or {}).get("linkml_meta", {})
        if HASH_SUBSET in linkml_meta.get("in_subset", []):
            identity.add(name)
    return identity


def compute_hash_id(entity: RegistryClass | RegistryProperty) -> str:
    """Compute a content-based hash_id from entity's HashSubset fields."""
    identity = _identity_fields(type(entity))
    return _digest({k: v for k, v in entity.model_dump().items() if k in identity})


def compute_hash_id_for(model_cls: type, fields: dict) -> str:
    """Compute the hash_id for an entity that has not been constructed yet.

    hash_id is the identifier in schemas/meta_model.yaml, so the generated
    models require it at construction — but a content hash can only be derived
    from the content itself. Builders therefore hash the field values they are
    about to pass, then construct once with the real hash_id, rather than
    constructing with a placeholder and mutating afterwards.

    `fields` must carry every HashSubset slot of `model_cls`; anything
    else may be present and is ignored. Omitting an identity slot raises,
    because the alternative is a silently different hash the next time the
    meta-model grows a slot — which would invalidate every stored hash_id in
    the registry without anything failing.
    """
    identity = _identity_fields(model_cls)
    missing = identity - set(fields)
    if missing:
        raise ValueError(
            f"{model_cls.__name__}: cannot hash — identity-defining field(s) "
            f"missing from `fields`: {sorted(missing)}"
        )
    return _digest({k: v for k, v in fields.items() if k in identity})


def _digest(content: dict) -> str:
    canonical = json.dumps(_normalize(content), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def assign_hash_id(entity: RegistryClass | RegistryProperty) -> RegistryClass | RegistryProperty:
    """Compute entity's hash_id from its current content, then suffix its name
    with the first 4 hex characters of the digest (e.g. "age" -> "age_a1b2").

    Mutates entity in place and returns it. Note: since name is part of the
    hashed content, the resulting hash_id will no longer match a fresh
    compute_hash_id() call on the entity after this mutation.
    """
    hash_id = compute_hash_id(entity)
    digest = hash_id.split(":", 1)[1]
    entity.hash_id = hash_id
    entity.name = f"{entity.name}_{digest[:4]}"
    return entity


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    if isinstance(value, list):
        normalized = [_normalize(val) for val in value]
        if all(isinstance(val, str) for val in normalized):
            # reference lists (properties/mixins) are unordered sets
            return sorted(normalized)
        return normalized
    return value
