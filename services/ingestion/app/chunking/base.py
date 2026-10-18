from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChunkCandidate:
    text: str
    page: int
    section: str | None


class Chunker(Protocol):
    def chunk(self, pages: list[tuple[int, str]]) -> list[ChunkCandidate]:
        """pages: list of (page_number, page_text), in order."""
        ...
