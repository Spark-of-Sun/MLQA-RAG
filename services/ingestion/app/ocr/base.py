from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class OcrPageResult:
    page_number: int
    text: str
    confidence: float  # 0.0-1.0
    flagged_for_review: bool


class OcrBackend(Protocol):
    def extract_pages(self, file_bytes: bytes, filename: str) -> list[OcrPageResult]: ...
