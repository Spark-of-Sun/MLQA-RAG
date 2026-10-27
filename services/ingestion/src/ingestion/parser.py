"""Document parser for PDF, HTML, and plain text formats."""

from __future__ import annotations

import re
import zlib
from html.parser import HTMLParser
from typing import NamedTuple


class PageText(NamedTuple):
    """Extracted text unit with page provenance."""

    page_num: int
    text: str


class ParseError(ValueError):
    """Raised when parsing fails or input is malformed."""


class OcrDisabledError(ParseError):
    """Raised when a page has no usable text layer and OCR is disabled (DR-15)."""


class _HTMLTextExtractor(HTMLParser):
    """Strips dangerous scripts and extracts text blocks from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._ignore = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag.lower() in ("script", "style", "noscript"):
            self._ignore = True
        elif tag.lower() in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style", "noscript"):
            self._ignore = False
        elif tag.lower() in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore:
            self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces).strip()


class DocumentParser:
    """Extracts text and page mapping from supported document types."""

    def __init__(self, *, ocr_enabled: bool = False) -> None:
        """Initialize parser with OCR flag."""
        self.ocr_enabled = ocr_enabled

    def parse(self, data: bytes, content_type: str) -> list[PageText]:
        """Parse document bytes into a sequence of PageText records."""
        if content_type == "application/pdf":
            return self._parse_pdf(data)
        if content_type == "text/html":
            return self._parse_html(data)
        if content_type in ("text/plain", "application/xml"):
            text = data.decode("utf-8", errors="replace").strip()
            return [PageText(page_num=1, text=text)]
        msg = f"Unsupported content type for parsing: {content_type}"
        raise ParseError(msg)

    def _parse_html(self, data: bytes) -> list[PageText]:
        html_str = data.decode("utf-8", errors="replace")
        parser = _HTMLTextExtractor()
        parser.feed(html_str)
        text = parser.get_text()
        if not text:
            msg = "HTML document contains no extractable text"
            raise ParseError(msg)
        return [PageText(page_num=1, text=text)]

    def _parse_pdf(self, data: bytes) -> list[PageText]:
        pages = self._extract_pdf_pages_simple(data)
        if not pages:
            msg = "Failed to extract pages from PDF"
            raise ParseError(msg)

        results: list[PageText] = []
        for page_idx, page_raw in enumerate(pages, start=1):
            cleaned = page_raw.strip()
            if not cleaned:
                if not self.ocr_enabled:
                    msg = f"Page {page_idx} has no usable text layer and OCR is disabled (DR-15)"
                    raise OcrDisabledError(msg)
                cleaned = "[quarantined: page requires OCR review]"
            results.append(PageText(page_num=page_idx, text=cleaned))

        return results

    def _extract_pdf_pages_simple(self, data: bytes) -> list[str]:
        """Extract text layer from PDF objects and content streams."""
        # Find all stream objects
        stream_pattern = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
        streams: list[bytes] = stream_pattern.findall(data)

        decompressed_chunks: list[str] = []
        for raw_stream in streams:
            try:
                decompressed = zlib.decompress(raw_stream)
                text = self._extract_stream_text(decompressed)
                if text:
                    decompressed_chunks.append(text)
            except zlib.error:
                # Plain uncompressed stream
                text = self._extract_stream_text(raw_stream)
                if text:
                    decompressed_chunks.append(text)

        if not decompressed_chunks:
            # Fallback regex search for text in string literals (Tj/TJ) in the whole file
            fallback_text = self._extract_stream_text(data)
            if fallback_text:
                return [fallback_text]
            return [""]

        # Group streams into pages (estimate or split if multiple pages)
        combined = "\n\n".join(decompressed_chunks)
        if "\x0c" in combined:
            return [p for p in combined.split("\x0c") if p.strip()]
        return [combined]

    def _extract_stream_text(self, stream_data: bytes) -> str:
        """Extract text operands from PDF text operators (Tj and TJ)."""
        text_parts: list[str] = []

        # Match single string operand: (Text) Tj
        tj_matches = re.finditer(rb"\((.*?)\)\s*Tj", stream_data, re.DOTALL)
        for m in tj_matches:
            raw = m.group(1).decode("latin1", errors="replace")
            text_parts.append(raw)

        # Match array operand: [(Text) -10 (More)] TJ
        tj_array_matches = re.finditer(rb"\[(.*?)\]\s*TJ", stream_data, re.DOTALL)
        for m in tj_array_matches:
            arr_content = m.group(1)
            str_items = re.findall(rb"\((.*?)\)", arr_content, re.DOTALL)
            joined = "".join(i.decode("latin1", errors="replace") for i in str_items)
            text_parts.append(joined)

        return " ".join(text_parts).strip()
