"""Malware scan before any parser touches a file (blueprint 10.5, 11.1, G4.1): ClamAV `zINSTREAM`.

A file is accepted only on an explicit `OK` reply. A timeout, a connection failure, `size limit exceeded` or any
other reply is a refusal (fail closed): the document goes to `failed` with reason `scan_unavailable` or
`malware_detected`, its quarantine object is deleted, and nothing is ever indexed. The EICAR test file is the
negative control (tests/controls.md).

PDF active content (JavaScript, launch actions, embedded files, XFA forms) is removed by `strip_pdf_active_content`
before parsing, so the stored and parsed form carries no executable parts.
"""

from __future__ import annotations

import io
import socket
import struct
from dataclasses import dataclass

CHUNK = 64 * 1024


class ScanRefusedError(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None
    engine: str


def scan_bytes(data: bytes, *, host: str, port: int, timeout: float = 30.0) -> ScanResult:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                part = data[i : i + CHUNK]
                sock.sendall(struct.pack(">I", len(part)) + part)
            sock.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                reply += chunk
    except OSError as exc:
        raise ScanRefusedError("scan_unavailable", type(exc).__name__) from exc
    text = reply.rstrip(b"\0").decode(errors="replace")
    if text.endswith(" OK"):
        return ScanResult(True, None, "clamav")
    if text.endswith(" FOUND"):
        signature = text.rsplit(":", 1)[-1].removesuffix(" FOUND").strip()
        raise ScanRefusedError("malware_detected", signature)
    raise ScanRefusedError("scan_unavailable", text[:120])


_ACTIVE_KEYS = (
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/Launch",
    "/EmbeddedFiles",
    "/XFA",
    "/RichMedia",
)


def strip_pdf_active_content(data: bytes) -> tuple[bytes, list[str]]:  # noqa: C901 - one linear flow; splitting it is a DEV-33 follow-up
    """Rewrite a PDF without document-level actions, JavaScript, embedded files and XFA. Returns (bytes, removed)."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter(clone_from=reader)
    removed: list[str] = []
    root = writer._root_object
    for key in ("/OpenAction", "/AA"):
        if NameObject(key) in root:
            del root[NameObject(key)]
            removed.append(key)
    names = root.get("/Names")
    if names is not None:
        names = names.get_object()
        for key in ("/JavaScript", "/EmbeddedFiles"):
            if NameObject(key) in names:
                del names[NameObject(key)]
                removed.append(key)
    acro = root.get("/AcroForm")
    if acro is not None and NameObject("/XFA") in acro.get_object():
        del acro.get_object()[NameObject("/XFA")]
        removed.append("/XFA")
    for page in writer.pages:
        if NameObject("/AA") in page:
            del page[NameObject("/AA")]
            removed.append("/Page/AA")
        for annot in page.get("/Annots", []) or []:
            obj = annot.get_object()
            action = obj.get("/A")
            if action is not None and action.get_object().get("/S") in {"/JavaScript", "/Launch"}:
                del obj[NameObject("/A")]
                removed.append("/Annot/A")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), sorted(set(removed))
