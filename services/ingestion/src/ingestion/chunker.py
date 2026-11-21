"""Structure-aware chunking (doc 11.1 step 7, 11.2).

* A new unit starts at every heading; text before the first heading is the **preamble** unit
  (parties, recitals, effective date), which the earlier design dropped (DEF-34).
* Consecutive table rows stay together; rows are never split.
* A unit above the maximum is split at block boundaries with about 10 percent overlap (recorded
  in ``meta``). A single block above the maximum is split at sentence boundaries.
* A unit below the minimum is merged into a neighbour in the same top-level section.
* Chunk text is always ``normalize(page text sliced at the stored spans)``, so it can be
  re-extracted from the original document at its page and offsets (gate G4.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from ingestion.headings import classify_line
from ingestion.model import (
    MAX_TOKENS,
    MIN_TOKENS,
    OVERLAP_RATIO,
    TARGET_HIGH,
    Block,
    ChunkDraft,
    ParsedDocument,
    Span,
    normalize_text,
)
from lmqa_models.tokenizer import HfTokenizer

if TYPE_CHECKING:
    from collections.abc import Sequence

_SENTENCE: Final = re.compile(r"(?<=[.;:?!])\s+(?=[A-Z(\[\"'])")
__all__ = ["ChunkConfig", "HfTokenizer", "Tokenizer", "chunk_document"]
_CLAUSE_KIND: Final = re.compile(r"^(?:Section|\d+(?:\.\d+)+)", re.IGNORECASE)


class Tokenizer(Protocol):
    """Counts tokens the way the embedding model does."""

    def count(self, text: str) -> int:
        """Number of tokens in ``text``."""
        ...


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    """Token bounds. Defaults are the document's; the MVP embedder lowers the maximum."""

    min_tokens: int = MIN_TOKENS
    target_high: int = TARGET_HIGH
    max_tokens: int = MAX_TOKENS
    overlap_ratio: float = OVERLAP_RATIO

    @classmethod
    def for_embedding(cls, max_seq: int) -> ChunkConfig:
        """Fit the bounds to an embedding model's sequence limit (bge-small: 512, bge-m3: 8192)."""
        return cls(
            target_high=min(TARGET_HIGH, int(max_seq * 0.85)),
            max_tokens=min(MAX_TOKENS, max_seq - 8),
        )


@dataclass(slots=True)
class _Piece:
    """A block range plus its token count (a block may have been split on sentences)."""

    page: int
    start: int
    end: int
    tokens: int
    kind: str
    table_id: int | None


@dataclass(slots=True)
class _Unit:
    kind: str
    heading: Block | None
    pieces: list[_Piece]
    section_path: str
    top: str

    @property
    def tokens(self) -> int:
        return sum(p.tokens for p in self.pieces)


def _hard_ranges(text: str, tok: Tokenizer, cfg: ChunkConfig) -> list[tuple[int, int]]:
    """Last resort for run-on text: cut at whitespace so every range fits the token maximum."""
    ranges: list[tuple[int, int]] = []
    start = 0
    per_char = max(1, tok.count(text)) / max(1, len(text))
    budget = max(40, int(cfg.target_high / per_char * 0.95))
    while start < len(text):
        end = min(len(text), start + budget)
        if end < len(text):
            cut = text.rfind(" ", start + 1, end)
            end = cut if cut > start else end
        while end - start > 20 and tok.count(text[start:end]) > cfg.max_tokens:  # noqa: PLR2004
            budget = int(budget * 0.9)
            end = start + budget
            cut = text.rfind(" ", start + 1, end)
            end = cut if cut > start else end
        ranges.append((start, end))
        start = end
        while start < len(text) and text[start] == " ":
            start += 1
    return ranges


def _split_block(
    doc: ParsedDocument, block: Block, tok: Tokenizer, cfg: ChunkConfig
) -> list[_Piece]:
    text = doc.slice(block.page, block.start, block.end)
    count = tok.count(text)
    if count <= cfg.max_tokens:
        return [_Piece(block.page, block.start, block.end, count, block.kind, block.table_id)]
    ranges: list[tuple[int, int]] = []
    cursor, buffer_start = 0, 0
    buffer_tokens = 0
    for match in [*_SENTENCE.finditer(text), None]:
        end = match.start() if match else len(text)
        n = tok.count(text[cursor:end])
        if buffer_tokens and buffer_tokens + n > cfg.target_high:
            ranges.append((buffer_start, cursor))
            buffer_start, buffer_tokens = cursor, 0
        buffer_tokens += n
        cursor = match.end() if match else len(text)
    if buffer_tokens:
        ranges.append((buffer_start, len(text)))
    pieces: list[_Piece] = []
    for lo, hi in ranges:
        part = text[lo:hi]
        n = tok.count(part)
        if n <= cfg.max_tokens:
            pieces.append(
                _Piece(
                    block.page, block.start + lo, block.start + hi, n, block.kind, block.table_id
                )
            )
            continue
        for h_lo, h_hi in _hard_ranges(part, tok, cfg):
            sub_part = part[h_lo:h_hi]
            pieces.append(
                _Piece(
                    block.page,
                    block.start + lo + h_lo,
                    block.start + lo + h_hi,
                    tok.count(sub_part),
                    block.kind,
                    block.table_id,
                )
            )
    return pieces


def _units(doc: ParsedDocument, tok: Tokenizer, cfg: ChunkConfig) -> list[_Unit]:
    units: list[_Unit] = []
    current: _Unit | None = None
    top = ""
    for block in doc.blocks:
        if block.kind == "heading":
            if block.level == 0:
                top = block.section_path
            current = _Unit("section", block, [], block.section_path, top)
            units.append(current)
        if block.kind == "table_row":
            if (
                current is None
                or current.kind != "table"
                or current.pieces[-1].table_id != block.table_id
            ):
                current = _Unit("table", None, [], block.section_path, top)
                units.append(current)
        elif current is None:
            current = _Unit("preamble", None, [], "", top)
            units.append(current)
        elif current.kind == "table":
            current = _Unit("section", None, [], block.section_path, top)
            units.append(current)
        assert current is not None  # noqa: S101
        current.pieces.extend(_split_block(doc, block, tok, cfg))
    return units


def _merge_small(units: list[_Unit], cfg: ChunkConfig) -> list[_Unit]:
    """Reach the minimum size: a tiny heading joins the unit it introduces (a body or a table).

    A preamble is never merged away, because a preamble chunk must exist (doc 11.1, DEF-34).
    """
    forward: list[_Unit] = []
    pending: _Unit | None = None
    for unit in units:
        if pending is not None:
            if pending.tokens + unit.tokens <= cfg.max_tokens:
                unit.pieces[:0] = pending.pieces
                unit.heading = pending.heading or unit.heading
                unit.section_path = pending.section_path or unit.section_path
            else:
                forward.append(pending)
            pending = None
        if unit.kind == "section" and unit.tokens < cfg.min_tokens:
            pending = unit
            continue
        forward.append(unit)
    if pending is not None:
        forward.append(pending)
    merged: list[_Unit] = []
    for unit in forward:  # leftovers (a short last unit): join the previous unit if it fits
        if (
            merged
            and unit.kind == "section"
            and unit.tokens < cfg.min_tokens
            and merged[-1].kind != "table"
            and merged[-1].tokens + unit.tokens <= cfg.max_tokens
        ):
            merged[-1].pieces.extend(unit.pieces)
        else:
            merged.append(unit)
    return merged


def _tail(doc: ParsedDocument, piece: _Piece, tok: Tokenizer, budget: float) -> _Piece | None:
    """Trailing text of ``piece`` within ``budget`` tokens: whole sentences, else words."""
    text = doc.slice(piece.page, piece.start, piece.end)
    cuts = [m.end() for m in _SENTENCE.finditer(text)]
    for cut in cuts:  # earliest cut first: keep as many trailing sentences as the budget allows
        n = tok.count(text[cut:])
        if 0 < n <= budget:
            return _Piece(piece.page, piece.start + cut, piece.end, n, piece.kind, piece.table_id)
    # No whole sentence fits (legal sentences are long): fall back to a word-boundary tail.
    per_char = max(1, tok.count(text)) / max(1, len(text))
    guess = max(0, len(text) - int(budget / per_char))
    cut = text.find(" ", guess)
    while 0 <= cut < len(text) - 1:
        n = tok.count(text[cut + 1 :])
        if 0 < n <= budget:
            return _Piece(
                piece.page, piece.start + cut + 1, piece.end, n, piece.kind, piece.table_id
            )
        cut = text.find(" ", cut + 1)
    return None


def _windows(
    unit: _Unit, cfg: ChunkConfig, doc: ParsedDocument, tok: Tokenizer
) -> tuple[list[list[_Piece]], bool]:
    """Split a unit into windows of at most ``target_high`` tokens with about 10 percent overlap."""
    if unit.tokens <= cfg.max_tokens:
        return [unit.pieces], False
    budget = cfg.target_high * cfg.overlap_ratio
    windows: list[list[_Piece]] = []
    window: list[_Piece] = []
    size = 0
    for piece in unit.pieces:
        if window and size + piece.tokens > cfg.target_high:
            windows.append(window)
            keep: list[_Piece] = []
            kept = 0
            for previous in reversed(window):
                if kept + previous.tokens > budget:
                    if not keep and previous.kind != "table_row":
                        tail = _tail(doc, previous, tok, budget)
                        if tail is not None:
                            keep.insert(0, tail)
                            kept += tail.tokens
                    break
                keep.insert(0, previous)
                kept += previous.tokens
            window, size = keep, kept
        window.append(piece)
        size += piece.tokens
    if window:
        windows.append(window)
    return windows, len(windows) > 1


def _spans(pieces: Sequence[_Piece]) -> list[Span]:
    spans: list[Span] = []
    for piece in pieces:
        if spans and spans[-1].page == piece.page and piece.start >= spans[-1].end:
            spans[-1] = Span(piece.page, spans[-1].start, piece.end)
        else:
            spans.append(Span(piece.page, piece.start, piece.end))
    return spans


def _kind(unit: _Unit, doc: ParsedDocument) -> str:
    if unit.kind == "preamble":
        return "preamble"
    if unit.kind == "table":
        return "table"
    if unit.heading is None:
        return "paragraph"
    soap = classify_line(doc.slice(unit.heading.page, unit.heading.start, unit.heading.end))
    if soap and soap.soap and soap.soap != "paragraph":
        return soap.soap
    if unit.heading.clause_no and _CLAUSE_KIND.match(unit.section_path.rsplit(" > ", 1)[-1] or ""):
        return "clause"
    return "section"


def chunk_document(
    doc: ParsedDocument, tok: Tokenizer, cfg: ChunkConfig | None = None
) -> list[ChunkDraft]:
    """Build chunk drafts in document order. Empty documents produce no chunks."""
    cfg = cfg or ChunkConfig()
    drafts: list[ChunkDraft] = []
    for unit in _merge_small(_units(doc, tok, cfg), cfg):
        windows, overlapped = _windows(unit, cfg, doc, tok)
        kind = _kind(unit, doc)
        for window in windows:
            spans = _spans(window)
            text = normalize_text(" ".join(doc.slice(s.page, s.start, s.end) for s in spans))
            if not text:
                continue
            heading = unit.heading
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    kind=kind,
                    text=text,
                    spans=spans,
                    section_path=unit.section_path,
                    clause_no=heading.clause_no if heading else None,
                    heading=heading.heading if heading else None,
                    token_count=max(1, tok.count(text)),
                    page_start=spans[0].page,
                    page_end=spans[-1].page,
                    meta={"overlap": overlapped, "structure": doc.structure},
                )
            )
    return drafts
