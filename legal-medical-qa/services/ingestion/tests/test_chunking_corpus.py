"""G4.2 chunk fidelity and G4.3 page correctness (automated proxy) on the real corpus."""

from __future__ import annotations

import io
import itertools
import re

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader

from ingestion.chunker import ChunkConfig, HfTokenizer, chunk_document
from ingestion.model import ChunkDraft, normalize_text
from ingestion.parsers import UnsupportedFormatError, detect_format, parse
from lmqa_testing.corpus import CorpusItem, load_corpus

pytestmark = [pytest.mark.integration, pytest.mark.stage4]
CFG = ChunkConfig.for_embedding(512)  # the MVP embedding model reads 512 tokens
CORPUS = load_corpus()


def _ids(items: list[CorpusItem]) -> list[str]:
    return [i.id[:40] for i in items]


@pytest.mark.parametrize("item", CORPUS, ids=_ids(CORPUS))
def test_every_real_document_parses_and_chunks_without_empty_chunks(
    item: CorpusItem, tokenizer: HfTokenizer
) -> None:
    doc = parse(item.data, item.format)
    chunks = chunk_document(doc, tokenizer, CFG)
    assert chunks, "a real document yields chunks"
    assert all(c.text.strip() for c in chunks), "no empty chunks"
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


@pytest.mark.parametrize("item", CORPUS, ids=_ids(CORPUS))
def test_g4_2_chunk_text_equals_a_fresh_re_extraction_at_the_stored_spans(
    item: CorpusItem, tokenizer: HfTokenizer
) -> None:
    """100% of chunks: re-parse the ORIGINAL bytes and slice at the stored page and offsets."""
    chunks = chunk_document(parse(item.data, item.format), tokenizer, CFG)
    fresh = parse(item.data, item.format)  # an independent run of the parser on the original file
    bad = []
    for c in chunks:
        rebuilt = normalize_text(" ".join(fresh.slice(s.page, s.start, s.end) for s in c.spans))
        if rebuilt != c.text:
            bad.append(c.ordinal)
    assert bad == [], f"{len(bad)} of {len(chunks)} chunks differ from the re-extracted text"


@pytest.mark.parametrize("item", CORPUS, ids=_ids(CORPUS))
def test_g4_2_token_bounds_page_ranges_and_spans_are_consistent(
    item: CorpusItem, tokenizer: HfTokenizer
) -> None:
    doc = parse(item.data, item.format)
    chunks = chunk_document(doc, tokenizer, CFG)
    assert max(c.token_count for c in chunks) <= CFG.max_tokens, "the maximum is a hard bound"
    for c in chunks:
        assert c.page_start == c.spans[0].page
        assert c.page_end == c.spans[-1].page >= c.page_start
        assert [s.page for s in c.spans] == sorted(s.page for s in c.spans)
        for s in c.spans:
            assert 0 <= s.start < s.end <= len(doc.pages[s.page - 1].text)
    soft = [c for c in chunks if c.kind not in {"preamble", "table"}]
    small = sum(c.token_count < CFG.min_tokens for c in soft)
    assert small <= max(2, 0.1 * len(soft)), (
        f"{small} prose chunks below the {CFG.min_tokens}-token minimum"
    )


def test_g4_2_every_contract_has_a_preamble_chunk(tokenizer: HfTokenizer) -> None:
    contracts = load_corpus(kind="contract")
    assert len(contracts) >= 4
    for item in contracts:
        chunks = chunk_document(parse(item.data, item.format), tokenizer, CFG)
        assert chunks[0].kind == "preamble", f"{item.id} lost the text before the first heading"
        assert chunks[0].text, "the preamble carries the parties and recitals"


def _shared_chars(first: ChunkDraft, second: ChunkDraft) -> int:
    return sum(
        max(0, min(a.end, b.end) - max(a.start, b.start))
        for a in first.spans
        for b in second.spans
        if a.page == b.page
    )


def test_overlong_units_are_split_with_about_ten_percent_overlap(tokenizer: HfTokenizer) -> None:
    pairs = with_overlap = 0
    for item in load_corpus():
        chunks = chunk_document(parse(item.data, item.format), tokenizer, CFG)
        for first, second in itertools.pairwise(chunks):
            if (
                first.meta.get("overlap")
                and second.meta.get("overlap")
                and first.section_path == second.section_path
            ):
                pairs += 1
                shared = _shared_chars(first, second)
                with_overlap += shared > 0
                assert shared <= 0.3 * max(1, sum(s.end - s.start for s in first.spans)), (
                    "overlap stays modest"
                )
    assert pairs >= 10, "the real corpus contains many split units"
    assert with_overlap / pairs >= 0.8, (
        f"only {with_overlap}/{pairs} split windows overlap their neighbour"
    )


def test_no_table_row_is_ever_cut_across_chunks(tokenizer: HfTokenizer) -> None:
    rows = 0
    for item in load_corpus():
        doc = parse(item.data, item.format)
        chunks = chunk_document(doc, tokenizer, CFG)
        for block in (b for b in doc.blocks if b.kind == "table_row"):
            rows += 1
            whole = any(
                s.page == block.page and s.start <= block.start and block.end <= s.end
                for c in chunks
                for s in c.spans
            )
            assert whole, f"{item.id}: a table row was split across chunks"
    assert rows >= 50, "the real corpus contains many table rows"


def test_g4_3_pdf_page_ranges_agree_with_an_independent_extractor(tokenizer: HfTokenizer) -> None:
    """Automated proxy for the human-verified page check: pypdf is a different PDF extractor."""
    item = load_corpus(kind="court_opinion")[0]
    chunks = chunk_document(parse(item.data, "pdf"), tokenizer, CFG)
    reader = PdfReader(io.BytesIO(item.data))
    pages = [set(re.findall(r"[a-z0-9]+", (p.extract_text() or "").lower())) for p in reader.pages]
    checked = exact = 0
    for c in chunks[::3]:
        words = re.findall(r"[a-z0-9]+", c.text.lower())
        if len(words) < 30:
            continue
        cited = set().union(*(pages[p - 1] for p in range(c.page_start, c.page_end + 1)))
        covered = sum(w in cited for w in words) / len(words)
        outside = set().union(
            *(pages[p] for p in range(len(pages)) if not c.page_start - 1 <= p <= c.page_end - 1)
        )
        checked += 1
        exact += covered >= 0.97
        assert covered >= 0.9, f"chunk {c.ordinal} words are mostly absent from its cited pages"
        del outside
    assert checked >= 20
    assert exact / checked >= 0.9, (
        f"only {exact}/{checked} chunks fully covered by their cited pages"
    )


def test_a_document_with_no_headings_is_flagged_fallback_never_silent(
    tokenizer: HfTokenizer,
) -> None:
    item = load_corpus(kind="court_opinion")[0]
    page = pdfium.PdfDocument(item.data)[40].get_textpage().get_text_range()
    body = " ".join(page.split()).encode()  # real prose, no line structure, so no headings
    doc = parse(body, "txt")
    assert doc.structure == "fallback"
    chunks = chunk_document(doc, tokenizer, CFG)
    assert chunks
    assert all(c.meta["structure"] == "fallback" for c in chunks)
    assert all(c.kind in {"preamble", "paragraph"} for c in chunks)


def test_a_page_without_a_text_layer_is_flagged_for_ocr_review_not_embedded(
    tokenizer: HfTokenizer,
) -> None:
    """A real page rasterized into an image-only PDF has no text layer (a scanner stand-in)."""
    item = load_corpus(kind="court_opinion")[0]
    source = pdfium.PdfDocument(item.data)
    image = source[3].render(scale=1.2).to_pil().convert("L")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    doc = parse(buffer.getvalue(), "pdf")
    assert [p.extraction for p in doc.pages] == ["none"]
    assert doc.blocks == ()
    assert chunk_document(doc, tokenizer, CFG) == [], (
        "nothing is chunked, so nothing can be embedded"
    )


@pytest.mark.parametrize(
    ("declared", "content_of"),
    [("docx", "pdf"), ("pdf", "html"), ("html", "pdf"), ("xml", "pdf"), ("pdf", "xml")],
)
def test_declared_type_must_match_the_magic_bytes(declared: str, content_of: str) -> None:
    pick = {
        "pdf": load_corpus(kind="court_opinion")[0],
        "html": load_corpus(kind="contract")[0],
        "xml": load_corpus(kind="regulation")[0],
    }[content_of]
    with pytest.raises(UnsupportedFormatError):
        detect_format(pick.data, declared)


def test_binary_and_oversized_input_is_refused() -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_format(b"\x00\x01\x02\x03" * 100, "txt")
    with pytest.raises(UnsupportedFormatError):
        detect_format(b"MZ" + b"\x00" * 64, "pdf")


def test_xml_with_an_external_entity_does_not_leak_a_local_file() -> None:
    hostile = (
        b'<?xml version="1.0"?><!DOCTYPE article [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<article><body><sec><title>T</title><p>&x;</p></sec></body></article>"
    )
    try:
        doc = parse(hostile, "xml")
    except Exception:  # noqa: BLE001 - refusing the document is also acceptable
        return
    assert "root:" not in "".join(p.text for p in doc.pages)
