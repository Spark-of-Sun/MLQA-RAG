"""Structure-aware chunking (blueprint 11.1 step 7, 11.2).

Chunks follow structural units: a new chunk starts at every heading and every numbered clause. Text
before the first structural boundary becomes a `preamble` chunk (parties, recitals, effective date), so
it is never dropped. Without any detected structure the chunker packs paragraphs and records
`structure = fallback`, which the library shows. Chunk text is source text with whitespace collapsed;
nothing is rewritten, so every chunk can be found again in the original.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ingestion.parsers import Block, clause_label, looks_like_heading

TARGET_CHARS = 1600  # about 400 tokens
MAX_CHARS = 2800  # about 700 tokens
MIN_CHARS = 200


@dataclass
class Chunk:
    ordinal: int
    kind: str  # preamble | section | paragraph
    section: str | None
    page_start: int | None
    page_end: int | None
    text: str

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def split_long(text: str) -> list[str]:
    """Split an overlong paragraph on sentence boundaries; hard-wrap on spaces as a last resort."""
    sentences = re.split(r"(?<=[.;:!?])\s+(?=[A-Z(\"'\d])", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > MAX_CHARS:
            cut = sentence.rfind(" ", 0, TARGET_CHARS)
            cut = cut if cut > 0 else TARGET_CHARS
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > TARGET_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return [p for p in pieces if p]


def build_chunks(blocks: list[Block]) -> tuple[list[Chunk], str]:
    has_structure = any(b.heading or looks_like_heading(b.text) or clause_label(b.text) for b in blocks)
    chunks: list[Chunk] = []
    parts: list[tuple[str, bool]] = []  # (text, is_heading)
    pages: list[int] = []
    heading_path: str | None = None
    section: str | None = None
    started = False  # True once the first structural unit after the preamble has begun
    prev_heading = False

    def has_body() -> bool:
        return any(not is_h for _, is_h in parts)

    def size() -> int:
        return sum(len(t) + 2 for t, _ in parts)

    def flush() -> None:
        if not parts:
            return
        text = "\n\n".join(t for t, _ in parts).strip()
        kind = "paragraph" if not has_structure else ("section" if started else "preamble")
        label = section or ("Preamble" if kind == "preamble" else None)
        if text:
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    kind=kind,
                    section=label,
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    text=text,
                )
            )
        parts.clear()
        pages.clear()

    for block in blocks:
        text = block.text
        is_heading = has_structure and (block.heading or looks_like_heading(text))
        label = None if (is_heading or not has_structure) else clause_label(text)

        if is_heading:
            if has_body():
                flush()
                started = True
            stacked = prev_heading and heading_path and parts
            heading_path = (f"{heading_path} › {text}" if stacked else text)[:160]
            section = heading_path
        elif label:
            if has_body():
                flush()
            started = True
            section = (f"{heading_path} › {label}" if heading_path else label)[:160]
        prev_heading = is_heading

        for piece in split_long(text) if len(text) > MAX_CHARS else [text]:
            if has_body() and size() + len(piece) > TARGET_CHARS and size() >= MIN_CHARS:
                flush()
                started = started or has_structure
            parts.append((piece, is_heading))
            if block.page is not None:
                pages.append(block.page)

    flush()
    return merge_small(chunks), "detected" if has_structure else "fallback"


def merge_small(chunks: list[Chunk], min_chars: int = 160) -> list[Chunk]:
    """Fold chunks under ~40 tokens (blueprint 11.1 minimum) into the next chunk, or the previous one at the end.

    Text is joined, never dropped, so the preamble and stray headings stay searchable and citable.
    """
    out: list[Chunk] = []
    carry: Chunk | None = None
    for c in chunks:
        if carry is not None:
            pages = [p for p in (carry.page_start, carry.page_end, c.page_start, c.page_end) if p is not None]
            c = Chunk(
                0,
                c.kind,
                c.section,
                min(pages) if pages else None,
                max(pages) if pages else None,
                f"{carry.text}\n\n{c.text}",
            )
            carry = None
        if len(c.text) < min_chars:
            carry = c
            continue
        out.append(c)
    if carry is not None:
        if out:
            last = out[-1]
            pages = [p for p in (last.page_start, last.page_end, carry.page_start, carry.page_end) if p is not None]
            out[-1] = Chunk(
                0,
                last.kind,
                last.section,
                min(pages) if pages else None,
                max(pages) if pages else None,
                f"{last.text}\n\n{carry.text}",
            )
        else:
            out.append(carry)
    for i, c in enumerate(out):
        c.ordinal = i
    return out
