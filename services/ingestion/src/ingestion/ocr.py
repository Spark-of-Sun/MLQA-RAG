"""OCR with per-page confidence (blueprint 11.1, 6.5, G4.5).

Pages without a usable text layer are rasterized with pypdfium2 (Apache-2.0/BSD; PyMuPDF is AGPL and avoided, 4.5)
at 300 dpi and recognized with Tesseract 5 (`tesseract <png> stdout tsv`), which reports a confidence per word.
A page's confidence is the character-weighted mean of its word confidences. Any page below `threshold` sends the
document to `ocr_review`: those pages are quarantined (never embedded, never in Qdrant) until a person accepts or
corrects them in the library's review screen (G4.5 property: no quarantined chunk is embedded).
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 80.0  # percent; calibrated against the corpus CER floor in eval/floors.toml
DPI = 300


class OcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrPage:
    number: int
    text: str
    confidence: float
    quarantined: bool


def needs_ocr(page_text: str) -> bool:
    letters = sum(ch.isalpha() for ch in page_text)
    return letters < 40  # scanned or image-only page


def _tesseract() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise OcrUnavailableError("tesseract 5 is not installed")
    return exe


def ocr_png(png: bytes, *, lang: str = "eng") -> tuple[str, float]:
    exe = _tesseract()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        path.write_bytes(png)
        out = subprocess.run(  # noqa: S603 - fixed argv; tesseract path from config, temp file path
            [exe, str(path), "stdout", "-l", lang, "--psm", "3", "tsv"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    if out.returncode != 0:
        raise OcrUnavailableError(f"tesseract failed ({out.returncode})")
    words: list[tuple[str, float]] = []
    lines: dict[tuple[int, int, int], list[str]] = {}
    for row in csv.DictReader(io.StringIO(out.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        conf = float(row.get("conf") or -1)
        if not text or conf < 0:
            continue
        words.append((text, conf))
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(text)
    total = sum(len(w) for w, _ in words)
    confidence = sum(len(w) * c for w, c in words) / total if total else 0.0
    return "\n".join(" ".join(v) for _, v in sorted(lines.items())), confidence


def ocr_pdf_pages(
    data: bytes, pages: list[int], *, threshold: float = DEFAULT_THRESHOLD
) -> list[OcrPage]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out: list[OcrPage] = []
    try:
        for number in pages:
            bitmap = pdf[number - 1].render(scale=DPI / 72).to_pil()
            buf = io.BytesIO()
            bitmap.save(buf, format="PNG")
            text, conf = ocr_png(buf.getvalue())
            out.append(OcrPage(number, text, conf, conf < threshold))
    finally:
        pdf.close()
    return out
