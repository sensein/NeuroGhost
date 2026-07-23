"""
converters/bbqs.py — Fetch BBQS schema from brain-bbqs.org and write to schemas/
---------------------------------------------------------------------------------
Source: https://brain-bbqs.org/bbqs-schema.linkml.yaml

BBQS (Brain Behavior Quantification and Synchronization) is an NIH-funded
multi-institution consortium. Their LinkML schema is already well-structured
and schema.org-anchored, making it one of the best-aligned sources in the
registry.

Because BBQS is already valid LinkML, this converter is a straight fetch-and-
save — no transformation needed. The ingest_linkml.py parser handles it
directly. We just ensure it lands in schemas/bbqs.yml at the right path.

The canonical URL is stable and maintained by the BBQS consortium.
"""

from __future__ import annotations
import httpx
from pathlib import Path

BBQS_URL = "https://brain-bbqs.org/bbqs-schema.linkml.yaml"
OUT_PATH  = Path("schemas/bbqs.yml")


def convert() -> str:
    """Fetch the BBQS LinkML YAML and return its content as a string."""
    print("[bbqs] Fetching BBQS schema from brain-bbqs.org…")
    resp = httpx.get(BBQS_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    content = resp.text
    # Quick sanity check
    if "classes:" not in content or "slots:" not in content:
        raise ValueError("Fetched content does not look like a valid LinkML schema")
    # Count classes and slots for reporting
    import yaml
    data = yaml.safe_load(content)
    n_classes = len(data.get("classes") or {})
    n_slots   = len(data.get("slots")   or {})
    print(f"[bbqs]   {n_classes} classes, {n_slots} slots, version {data.get('version','?')}")
    return content


def run(out_path: Path = OUT_PATH) -> None:
    content = convert()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"[bbqs] Wrote {out_path}")


if __name__ == "__main__":
    run()
