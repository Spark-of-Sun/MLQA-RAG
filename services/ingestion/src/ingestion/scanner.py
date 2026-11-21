"""Malware and content scanning before any parser runs (doc 11.1 step 3).

Two layers. ``StaticChecks`` always run: size limit, PDF active content (JavaScript, embedded
files, launch actions), archive decompression bombs and the EICAR antivirus test signature.
``ClamdScanner`` speaks the real clamd INSTREAM protocol to a ClamAV daemon. A file that fails is
deleted and its document is marked ``failed`` with a reason code; it is never parsed or indexed.

Design note: the document says PDF active content is *removed*. The MVP is stricter and *rejects*
such a PDF, which is safe and simple; sanitizing is a later improvement.
"""

from __future__ import annotations

import asyncio
import io
import re
import struct
import zipfile
from dataclasses import dataclass
from typing import Final, Protocol

MAX_BYTES: Final = 200 * 1024 * 1024
MAX_UNCOMPRESSED_RATIO: Final = 100
MAX_UNCOMPRESSED_BYTES: Final = 1024 * 1024 * 1024
_EICAR: Final = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
_PDF_ACTIVE: Final = re.compile(rb"/(JavaScript|JS|EmbeddedFile|Launch|OpenAction|AA|RichMedia)\b")
_CHUNK: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The verdict. ``reason`` is a stable code stored on the document, never free text."""

    clean: bool
    reason: str | None = None


class Scanner(Protocol):
    """Anything that can scan bytes."""

    async def scan(self, data: bytes) -> ScanResult:
        """Return whether ``data`` is safe to hand to a parser."""
        ...


class StaticChecks:
    """Checks that need no external service and always run."""

    async def scan(self, data: bytes) -> ScanResult:
        """Size, EICAR, PDF active content and archive bombs."""
        if len(data) > MAX_BYTES:
            return ScanResult(clean=False, reason="size_limit")
        if _EICAR in data:
            return ScanResult(clean=False, reason="malware_eicar")
        if data[:5] == b"%PDF-" and _PDF_ACTIVE.search(data):
            return ScanResult(clean=False, reason="pdf_active_content")
        if data[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    total = sum(i.file_size for i in archive.infolist())
                    if total > MAX_UNCOMPRESSED_BYTES or total > MAX_UNCOMPRESSED_RATIO * max(
                        1, len(data)
                    ):
                        return ScanResult(clean=False, reason="decompression_bomb")
            except zipfile.BadZipFile:
                return ScanResult(clean=False, reason="malformed_archive")
        return ScanResult(clean=True)


class ClamdScanner:
    """ClamAV via the clamd INSTREAM command over TCP."""

    def __init__(self, host: str, port: int = 3310, timeout: float = 60.0) -> None:
        """Point at a clamd daemon."""
        self._host, self._port, self._timeout = host, port, timeout

    async def scan(self, data: bytes) -> ScanResult:
        """Stream the bytes to clamd. Any failure to scan counts as NOT clean (fail closed)."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), self._timeout
            )
            writer.write(b"zINSTREAM\0")
            for start in range(0, len(data), _CHUNK):
                piece = data[start : start + _CHUNK]
                writer.write(struct.pack(">I", len(piece)) + piece)
            writer.write(struct.pack(">I", 0))
            await writer.drain()
            reply = (await asyncio.wait_for(reader.read(4096), self._timeout)).rstrip(b"\0\n")
            writer.close()
        except OSError, TimeoutError:
            return ScanResult(clean=False, reason="scanner_unavailable")
        if reply.endswith(b"OK"):
            return ScanResult(clean=True)
        return ScanResult(
            clean=False, reason="malware_detected" if b"FOUND" in reply else "scanner_error"
        )


class CompositeScanner:
    """Runs every scanner; the first failure wins."""

    def __init__(self, *scanners: Scanner) -> None:
        """Compose scanners in order."""
        self._scanners = scanners

    async def scan(self, data: bytes) -> ScanResult:
        """Return the first failing verdict, else clean."""
        for scanner in self._scanners:
            result = await scanner.scan(data)
            if not result.clean:
                return result
        return ScanResult(clean=True)
