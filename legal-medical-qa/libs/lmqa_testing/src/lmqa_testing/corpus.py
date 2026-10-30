"""Load real corpus items for tests (doc 19.1 R1 and R3). The manifest is the only fixture source.

A hash mismatch or a missing licence fails loudly: tests never run on an unverified document.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lmqa_db.bootstrap import repo_root


class CorpusMissingError(RuntimeError):
    """The corpus documents are not on disk. They are fetched, never committed (rule R3)."""


EXTENSIONS = {"html": "htm", "jats": "xml", "spl": "xml"}


@dataclass(frozen=True, slots=True)
class CorpusItem:
    """One manifest entry with its verified bytes."""

    id: str
    title: str
    format: str
    domain: str
    kind: str
    license: str
    source_url: str
    data: bytes


def load_corpus(domain: str | None = None, kind: str | None = None) -> list[CorpusItem]:
    """Return verified items, optionally filtered. Raises on a missing file or hash mismatch."""
    root = Path(repo_root()) / "corpus"
    manifest = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))["item"]
    items: list[CorpusItem] = []
    for entry in manifest:
        if (domain and entry["domain"] != domain) or (kind and entry["kind"] != kind):
            continue
        if not entry.get("license"):
            msg = f"corpus item {entry['id']} has no licence"
            raise ValueError(msg)
        path = root / "data" / f"{entry['id']}.{EXTENSIONS.get(entry['format'], entry['format'])}"
        if not path.is_file():
            msg = (
                f"corpus document {entry['id']} is missing: the real public documents are fetched, not "
                "committed. Run `make load-corpus` (uv run python corpus/fetchers.py) once, then re-run the tests."
            )
            raise CorpusMissingError(msg)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            msg = f"corpus item {entry['id']} does not match its recorded SHA-256"
            raise ValueError(msg)
        items.append(
            CorpusItem(
                entry["id"],
                entry["title"],
                entry["format"],
                entry["domain"],
                entry["kind"],
                entry["license"],
                entry["source_url"],
                data,
            )
        )
    return items
