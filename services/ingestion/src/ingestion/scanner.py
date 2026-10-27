"""Malware, magic bytes, and active content scanner for documents."""

from __future__ import annotations

import re

EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

PDF_MAGIC = b"%PDF-"
HTML_PATTERNS = [
    re.compile(rb"<!doctype\s+html", re.IGNORECASE),
    re.compile(rb"<html", re.IGNORECASE),
]

# Suspicious active content PDF tags per Master §11.1 Step 3 and Gate G4.1
PDF_ACTIVE_CONTENT_TAGS = [
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/EmbeddedFiles",
    b"/RichMedia",
    b"/XFA",
]


class ScanValidationError(ValueError):
    """Raised when document scan detects malware, active content, or type mismatch."""


class DocumentScanner:
    """Validates files against malware, magic byte discrepancies, and active content."""

    def __init__(self, max_size_bytes: int = 50 * 1024 * 1024) -> None:
        """Initialize scanner with size threshold."""
        self.max_size_bytes = max_size_bytes

    def scan(self, data: bytes, declared_content_type: str) -> None:
        """Perform comprehensive hygiene and security checks on file bytes."""
        self._check_size(data)
        self._check_antivirus(data)
        self._check_type_and_active_content(data, declared_content_type)

    def _check_size(self, data: bytes) -> None:
        if len(data) == 0:
            msg = "Empty file rejected"
            raise ScanValidationError(msg)
        if len(data) > self.max_size_bytes:
            msg = f"File size {len(data)} exceeds limit {self.max_size_bytes}"
            raise ScanValidationError(msg)

    def _check_antivirus(self, data: bytes) -> None:
        if EICAR_SIGNATURE in data:
            msg = "Antivirus alert: EICAR test signature detected"
            raise ScanValidationError(msg)

    def _check_type_and_active_content(self, data: bytes, declared_content_type: str) -> None:
        if declared_content_type == "application/pdf":
            self._scan_pdf(data)
        elif declared_content_type == "text/html":
            self._scan_html(data)
        elif declared_content_type == "text/plain":
            self._scan_text(data)

    def _scan_pdf(self, data: bytes) -> None:
        if not data.startswith(PDF_MAGIC):
            msg = "PDF magic byte header missing (%PDF-)"
            raise ScanValidationError(msg)
        for tag in PDF_ACTIVE_CONTENT_TAGS:
            if tag in data:
                tag_repr = tag.decode("latin1", errors="replace")
                msg = f"PDF active content detected ({tag_repr})"
                raise ScanValidationError(msg)

    def _scan_html(self, data: bytes) -> None:
        has_html_sig = any(p.search(data[:1024]) for p in HTML_PATTERNS)
        if not has_html_sig and not data.strip().startswith(b"<"):
            msg = "HTML signature missing in document header"
            raise ScanValidationError(msg)

    def _scan_text(self, data: bytes) -> None:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"Invalid text encoding: {exc}"
            raise ScanValidationError(msg) from exc
