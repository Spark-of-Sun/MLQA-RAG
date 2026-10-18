from __future__ import annotations

from app.ocr import FakeOcrBackend, get_ocr_backend


def test_get_ocr_backend_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("OCR_ENGINE", raising=False)
    backend = get_ocr_backend()
    assert isinstance(backend, FakeOcrBackend)


def test_fake_ocr_single_page():
    backend = FakeOcrBackend()
    pages = backend.extract_pages(b"hello world", "doc.pdf")
    assert len(pages) == 1
    assert pages[0].text == "hello world"
    assert pages[0].confidence == 0.95
    assert pages[0].flagged_for_review is False


def test_fake_ocr_multi_page_split_on_form_feed():
    backend = FakeOcrBackend()
    pages = backend.extract_pages(b"page one\x0cpage two", "doc.pdf")
    assert len(pages) == 2
    assert pages[0].text == "page one"
    assert pages[1].text == "page two"
    assert pages[1].page_number == 2


def test_fake_ocr_flags_low_confidence():
    backend = FakeOcrBackend(fixed_confidence=0.5, low_confidence_threshold=0.7)
    pages = backend.extract_pages(b"scanned text", "doc.pdf")
    assert pages[0].flagged_for_review is True
