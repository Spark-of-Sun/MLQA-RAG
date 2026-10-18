from __future__ import annotations

import re

from .base import ChunkCandidate

_SECTION_PATTERN = re.compile(
    r"(?m)^\s*(?:Section\s+)?(\d+(?:\.\d+)+|\d+[.)])\s+(.*)$"
)

class LegalClauseChunker:
    """Splits by clause/section numbering (e.g. '4.2 Termination'), per
    docs/architecture.md §4 — preserves the unit a legal citation needs to
    point to, rather than a fixed token window.
    """

    def chunk(self, pages: list[tuple[int, str]]) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        for page_number, page_text in pages:
            matches = list(_SECTION_PATTERN.finditer(page_text))
            if not matches:
                if page_text.strip():
                    candidates.append(ChunkCandidate(text=page_text.strip(), page=page_number, section=None))
                continue
            for i, match in enumerate(matches):
                section_number = match.group(1)
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
                clause_text = page_text[start:end].strip()
                if clause_text:
                    candidates.append(ChunkCandidate(text=clause_text, page=page_number, section=section_number))
        return candidates
