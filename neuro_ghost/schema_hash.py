"""
File-level content hashing for whole schema sources.

Every SchemaSource carries a ``content_hash`` — the SHA-256 of the schema's
raw text, canonicalised so that cosmetic-only differences (line endings,
leading/trailing whitespace) don't change it. This is a FILE-level
fingerprint, deliberately distinct from the per-entity ``sha256_hash`` on
RegistryClass/RegistryProperty:

  * the entity hash answers "is this *concept* already known?" (dedup of
    classes/properties across schemas), and
  * this file hash answers "is this whole *file* already in the registry?" —
    so a schema that is byte-for-byte (modulo whitespace) identical to one we
    already ingested can be rejected up front, before any ingestion work, and
    the browser UI can pre-check a dropped/pasted file against known sources.

Both the ingest pipeline (here) and the UI must produce the SAME hash for the
same text, so the canonicalisation is intentionally trivial and easy to mirror
in JS: normalise CR/CRLF to LF, strip outer whitespace, end with a single
trailing newline, then hash the UTF-8 bytes. (JSON schemas are converted to
LinkML on ingest, so the stored form differs from the raw paste — a known
limitation: the UI pre-check only catches identical LinkML re-submissions.)
"""
from __future__ import annotations

import hashlib


def canonicalize(text: str) -> str:
    """Normalise a schema's raw text so cosmetic-only edits hash identically."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip() + "\n"


def content_hash(text: str) -> str:
    """SHA-256 hex digest of a schema's canonicalised raw text."""
    return hashlib.sha256(canonicalize(text).encode("utf-8")).hexdigest()
