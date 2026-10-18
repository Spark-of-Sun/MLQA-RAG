from __future__ import annotations

import os

from .base import OcrPageResult


class TesseractBackend:
    """Real local substitute — Tesseract via pytesseract, pages rasterized
    with pdf2image (poppler-utils). Heavy deps live in the optional
    '[real]' extra and are imported lazily so this module can be imported
    without them installed; instantiating this class without them raises
    a clear error instead of an ImportError traceback.
    """

    def __init__(self, low_confidence_threshold: float | None = None):
        self.low_confidence_threshold = low_confidence_threshold or float(
            os.environ.get("OCR_LOW_CONFIDENCE_THRESHOLD", "0.70")
        )

    def extract_pages(self, file_bytes: bytes, filename: str) -> list[OcrPageResult]:
        try:
            import pytesseract
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError(
                "TesseractBackend requires the 'real' extra: "
                "pip install -e '.[real]' plus the tesseract-ocr + poppler-utils system packages"
            ) from exc

        images = convert_from_bytes(file_bytes)
        results = []
        for i, image in enumerate(images, start=1):
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            words = [w for w in data["text"] if w.strip()]
            confidences = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and c != "-1"]
            page_text = " ".join(words)
            avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
            results.append(
                OcrPageResult(
                    page_number=i,
                    text=page_text,
                    confidence=avg_confidence,
                    flagged_for_review=avg_confidence < self.low_confidence_threshold,
                )
            )
        return results

