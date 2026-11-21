"""Turn an uploaded file into ordered text blocks with page numbers and heading flags (blueprint 11.1).

Structured sources keep their structure: DOCX heading styles, HTML <h1>-<h6>, and section titles in JATS
(PubMed Central), SPL (DailyMed drug labels) and eCFR XML. PDFs use the text layer; a page without one is
counted, never guessed at (OCR is a later stage), and a PDF with no text at all is rejected.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeET
from defusedxml.common import DefusedXmlException

_WS = re.compile(r"\s+")
# pypdf logs one warning per font per page for some PDFs (for example "fontTools is required ...").
# They are not errors; keep real errors visible and the server log readable.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class ParseError(ValueError):
    """The file cannot be turned into searchable text. The message is shown to the uploader."""


@dataclass
class Block:
    text: str
    page: int | None = None
    heading: bool = False


@dataclass
class ParsedDocument:
    blocks: list[Block]
    page_count: int | None = None
    title: str | None = None
    pages_without_text: list[int] = field(default_factory=list)


def clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\u00ad", "")).strip()


FILE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".txt": "txt",
    ".md": "txt",
}


def detect_type(filename: str, data: bytes) -> str:
    """File type from the extension, confirmed by magic bytes (blueprint 11.1 step 3)."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = FILE_TYPES.get(ext)
    if kind is None:
        raise ParseError("Unsupported file type. Upload PDF, DOCX, HTML, XML, TXT or MD.")
    head = data[:1024].lstrip()
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        raise ParseError("The file is not a valid PDF.")
    if kind == "docx" and not data.startswith(b"PK"):
        raise ParseError("The file is not a valid DOCX.")
    if kind in {"txt", "html", "xml"}:
        if b"\x00" in data[:4096]:
            raise ParseError("The file looks binary, not text.")
        if kind == "xml" and not head.startswith(b"<"):
            raise ParseError("The file is not valid XML.")
    return kind


def parse(kind: str, data: bytes) -> ParsedDocument:
    parser = {"pdf": parse_pdf, "docx": parse_docx, "html": parse_html, "xml": parse_xml, "txt": parse_text}
    doc = parser[kind](data)
    doc.blocks = [b for b in doc.blocks if b.text]
    if not doc.blocks:
        if kind == "pdf":
            raise ParseError("This PDF has no text layer (scanned). OCR is not available yet.")
        raise ParseError("No text found in the file.")
    return doc


# ---------------------------------------------------------------------------- text and markdown
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_text(data: bytes) -> ParsedDocument:
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", _decode(data)):
        stripped = para.strip()
        if not stripped:
            continue
        md = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if md and "\n" not in stripped:
            blocks.append(Block(clean(md.group(1)), heading=True))
        else:
            blocks.append(Block(clean(stripped)))
    return ParsedDocument(blocks=blocks)


# ---------------------------------------------------------------------------- PDF
def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("The PDF is password-protected.")
        pages = list(reader.pages)
    except PdfReadError as exc:
        raise ParseError("The PDF could not be read.") from exc
    if len(pages) > 2000:
        raise ParseError("The PDF has more than 2,000 pages.")
    title = None
    try:
        meta_title = reader.metadata.title if reader.metadata else None
        title = clean(str(meta_title)) if meta_title else None
    except PdfReadError, ValueError, TypeError:
        title = None
    blocks: list[Block] = []
    empty: list[int] = []
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except PdfReadError, ValueError, KeyError, TypeError:
            text = ""
        if len(text.strip()) < 20:
            empty.append(number)
            continue
        blocks.extend(Block(p, page=number) for p in _pdf_paragraphs(text))
    return ParsedDocument(blocks=blocks, page_count=len(pages), title=title, pages_without_text=empty)


def _pdf_paragraphs(text: str) -> list[str]:
    """Rejoin PDF lines into paragraphs: break on blank lines, headings, or a short line ending a sentence."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    widths = sorted(len(ln) for ln in lines if ln.strip())
    typical = widths[int(len(widths) * 0.8)] if widths else 80
    paras: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paras.append(clean(" ".join(current)))
            current.clear()

    for line in lines:
        s = line.strip()
        if not s:
            flush()
            continue
        if looks_like_heading(s):
            flush()
            paras.append(clean(s))
            continue
        current.append(s)
        if s[-1:] in ".:;?!" and len(s) < 0.75 * typical:
            flush()
    flush()
    return [p for p in paras if p]


# ---------------------------------------------------------------------------- DOCX
def parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ParseError("The DOCX could not be read.") from exc
    blocks: list[Block] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = clean(item.text)
            style = (item.style.name if item.style is not None else "") or ""
            blocks.append(Block(text, heading=style.startswith(("Heading", "Title"))))
        elif isinstance(item, Table):
            for row in item.rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = clean(cell.text)
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                if cells:
                    blocks.append(Block(" | ".join(cells)))
    title = clean(document.core_properties.title or "") or None
    return ParsedDocument(blocks=blocks, title=title)


# ---------------------------------------------------------------------------- HTML
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "tr",
    "table",
    "section",
    "article",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "dd",
    "dt",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "footer",
    "center",
    "hr",
}
_SKIP_TAGS = {"script", "style", "head", "noscript", "template", "svg"}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title: str | None = None
        self._buf: list[str] = []
        self._skip = 0
        self._heading = 0
        self._in_title = False
        self._cell = False

    def _flush(self) -> None:
        text = clean("".join(self._buf))
        self._buf.clear()
        if text:
            self.blocks.append(Block(text, heading=self._heading > 0))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag in {"td", "th"}:
            if self._cell:
                self._buf.append(" | ")
            self._cell = True
        if tag in _BLOCK_TAGS:
            self._flush()
            if tag == "tr":
                self._cell = False
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = max(0, self._heading - 1)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = clean((self.title or "") + " " + data) or None
        if self._skip:
            return
        self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def parse_html(data: bytes) -> ParsedDocument:
    parser = _HTMLText()
    parser.feed(_decode(data))
    parser.close()
    return ParsedDocument(blocks=parser.blocks, title=parser.title)


# ---------------------------------------------------------------------------- XML (JATS, SPL, eCFR)
_XML_HEADING = {"article-title", "title", "head", "hed", "subject"}
_XML_LEAF = {"p", "paragraph", "item", "li", "caption", "tr", "fp", "td", "list-item", "def", "term", "label"}
_XML_SKIP = {
    "ref-list",
    "contrib-group",
    "aff",
    "author-notes",
    "permissions",
    "history",
    "funding-group",
    "kwd-group",
    "counts",
    "journal-meta",
    "pub-date",
    "article-id",
    "custom-meta-group",
    "object-id",
    "fn-group",
    "author",
    "representedorganization",
    "manufacturedproduct",
    "code",
    "id",
    "effectivetime",
    "setid",
    "versionnumber",
    "xref",
    "ext-link",
    "uri",
    "cfrtoc",
    "auth",
    "source",
    "edno",
    "fr",
}


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def parse_xml(data: bytes) -> ParsedDocument:
    try:
        root = SafeET.fromstring(data)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise ParseError("The XML could not be parsed safely.") from exc
    blocks: list[Block] = []
    title: str | None = None

    def text_of(el: Element) -> str:
        parts: list[str] = []
        for node in el.iter():
            if _local(node.tag) in _XML_SKIP and node is not el:
                continue
            if node.text:
                parts.append(node.text)
            if node.tail and node is not el:
                parts.append(node.tail)
        return clean(" ".join(parts))

    def walk(el: Element) -> None:
        nonlocal title
        tag = _local(el.tag)
        if tag in _XML_SKIP:
            return
        if tag in _XML_HEADING:
            text = text_of(el)
            if text:
                if title is None and tag in {"article-title", "title"}:
                    title = text
                blocks.append(Block(text, heading=True))
            return
        if tag in _XML_LEAF:
            if tag == "tr":
                cells = [text_of(c) for c in el if _local(c.tag) in {"td", "th"}]
                text = " | ".join(c for c in cells if c)
            else:
                text = text_of(el)
            if text:
                blocks.append(Block(text))
            return
        for child in el:
            walk(child)

    walk(root)
    return ParsedDocument(blocks=blocks, title=title)


# ---------------------------------------------------------------------------- heading heuristics
_CLAUSE = re.compile(
    r"^(?:(?:ARTICLE|Article|SECTION|Section|SCHEDULE|Schedule|EXHIBIT|Exhibit|PART|Part)\s+[\dIVXLC]+[A-Za-z]?"
    r"(?:\.\d+)*|§+\s*\d+(?:\.\d+)*|\d{1,2}(?:\.\d{1,2}){0,3}\.?)\s+\S"
)
_MEDICAL = re.compile(
    r"^(?:Subjective|Objective|Assessment|Plan|History of Present Illness|HPI|Medications|Allergies|"
    r"Impression|Diagnosis|Findings|Chief Complaint|Physical Exam(?:ination)?|Past Medical History)\s*:?\s*$",
    re.IGNORECASE,
)


def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _MEDICAL.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.85 and len(s.split()) <= 12:
        return not s.endswith((",", ";"))
    return bool(_CLAUSE.match(s)) and len(s) <= 70 and not s.rstrip().endswith((",", ";"))


def clause_label(text: str) -> str | None:
    """A paragraph that opens a numbered clause ("Section 4.2 Termination. ...") names its section."""
    m = _CLAUSE.match(text)
    if not m:
        return None
    head = re.split(r"(?<=[a-z\)])\.\s|:\s", text, maxsplit=1)[0]
    return head[:100].strip() or None
