from __future__ import annotations

from .base import OcrPageResult


class FakeOcrBackend:
    """Deterministic OCR stand-in for local unit tests and offline dev —
    treats the input bytes as already-decoded UTF-8 text (one page, unless
    the text contains a form-feed \\x0c which splits pages, matching how a
    real multi-page extraction would be structured). Never used in the
    Docker image — see TesseractBackend for the real local substitute.
    """

    def __init__(self, low_confidence_threshold: float = 0.70, fixed_confidence: float = 0.95):
        self.low_confidence_threshold = low_confidence_threshold
        self.fixed_confidence = fixed_confidence

    def extract_pages(self, file_bytes: bytes, filename: str) -> list[OcrPageResult]:
        text = file_bytes.decode("utf-8", errors="replace")
        pages_text = text.split("\x0c") if "\x0c" in text else [text]
        results = []
        for i, page_text in enumerate(pages_text, start=1):
            results.append(
                OcrPageResult(
                    page_number=i,
                    text=page_text,
                    confidence=self.fixed_confidence,
                    flagged_for_review=self.fixed_confidence < self.low_confidence_threshold,
                )
            )
        return results
