import os

from .base import OcrBackend, OcrPageResult
from .fake_backend import FakeOcrBackend


def get_ocr_backend(engine: str | None = None) -> OcrBackend:
    engine = engine or os.environ.get("OCR_ENGINE", "fake")
    if engine == "tesseract":
        from .tesseract_backend import TesseractBackend

        return TesseractBackend()
    if engine == "fake":
        return FakeOcrBackend()
    raise ValueError(f"unknown OCR_ENGINE: {engine}")


__all__ = ["OcrBackend", "OcrPageResult", "FakeOcrBackend", "get_ocr_backend"]
