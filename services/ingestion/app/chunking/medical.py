from __future__ import annotations

import re

from .base import ChunkCandidate

_SOAP_HEADERS = ("Subjective", "Objective", "Assessment", "Plan")
_SOAP_PATTERN = re.compile(r"(?m)^\s*(" + "|".join(_SOAP_HEADERS) + r")\s*:\s*$")


class SoapNoteChunker:
    """Splits by SOAP note fields (Subjective/Objective/Assessment/Plan)
    or falls back to an 'Encounter' section, per docs/architecture.md §4 —
    preserves the clinical unit a citation needs to point to.
    """

    def chunk(self, pages: list[tuple[int, str]]) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        for page_number, page_text in pages:
            matches = list(_SOAP_PATTERN.finditer(page_text))
            if not matches:
                if page_text.strip():
                    candidates.append(ChunkCandidate(text=page_text.strip(), page=page_number, section="Encounter"))
                continue
            for i, match in enumerate(matches):
                section_name = match.group(1)
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(page_text)
                field_text = page_text[start:end].strip()
                if field_text:
                    candidates.append(ChunkCandidate(text=field_text, page=page_number, section=section_name))
        return candidates
