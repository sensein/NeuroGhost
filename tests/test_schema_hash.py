"""Unit tests for the file-level schema content hash (schema_hash.py)."""
from schema_hash import canonicalize, content_hash


def test_cosmetic_differences_hash_identically():
    """CRLF vs LF and leading/trailing whitespace must not change the hash —
    the same schema re-uploaded with different line endings is still 'the same
    file'."""
    base = "id: https://example.org/s\nname: s\nclasses:\n  Thing: {}"
    crlf = base.replace("\n", "\r\n")
    padded = f"\n\n  {base}  \n\n"
    assert content_hash(base) == content_hash(crlf) == content_hash(padded)


def test_content_difference_changes_hash():
    assert content_hash("name: a\n") != content_hash("name: b\n")


def test_canonicalize_is_normalised_form():
    assert canonicalize("  a: 1\r\nb: 2  \n\n") == "a: 1\nb: 2\n"
