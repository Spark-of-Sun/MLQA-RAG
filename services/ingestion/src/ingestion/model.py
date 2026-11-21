"""Parsed documents, structural blocks and chunk drafts (doc 11.1, 11.2).

A parser produces *page text* and *blocks*. A block is a character range inside one page's text,
with the structure the chunker needs. Chunks are built from block ranges, so the text of any
chunk can be re-extracted from the original file at its stored page and offsets (G4.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

TARGET_LOW: Final = 300
TARGET_HIGH: Final = 700
MIN_TOKENS: Final = 40
MAX_TOKENS: Final = 1200
OVERLAP_RATIO: Final = 0.10


def normalize_text(text: str) -> str:
    """Whitespace-normalize: the form in which chunk text is compared and hashed."""
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class PageText:
    """The extracted text of one page (an XML or HTML source is one logical page)."""

    number: int
    text: str
    extraction: str  # 'text_layer', 'structured', 'ocr' or 'none' (no usable text)
    ocr_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Block:
    """A range of one page's text with structural metadata."""

    page: int
    start: int
    end: int
    kind: str  # 'heading', 'paragraph', 'table_row', 'footnote'
    level: int = 0  # heading depth (0 = top)
    table_id: int | None = None
    section_path: str = ""
    clause_no: str | None = None
    heading: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """The output of a parser."""

    pages: tuple[PageText, ...]
    blocks: tuple[Block, ...]
    format: str
    structure: str  # 'detected' or 'fallback' (paragraph chunks; shown as a warning)
    domain_hint: str = "legal"

    def slice(self, page: int, start: int, end: int) -> str:
        """Return the exact characters of a block range."""
        return self.pages[page - 1].text[start:end]


@dataclass(frozen=True, slots=True)
class Span:
    """A contiguous range of one page that a chunk covers."""

    page: int
    start: int
    end: int


@dataclass(slots=True)
class ChunkDraft:
    """A chunk before it is encrypted and stored."""

    ordinal: int
    kind: str
    text: str
    spans: list[Span]
    section_path: str
    clause_no: str | None
    heading: str | None
    token_count: int
    page_start: int
    page_end: int
    quarantined: bool = False
    ocr_confidence_min: float | None = None
    ocr_confidence_mean: float | None = None
    meta: dict[str, object] = field(default_factory=dict[str, object])
