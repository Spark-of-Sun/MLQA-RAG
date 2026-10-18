from __future__ import annotations

from common.models import TenantIndustry

from app.chunking import LegalClauseChunker, SoapNoteChunker, get_chunker


def test_get_chunker_selects_by_industry():
    assert isinstance(get_chunker(TenantIndustry.LEGAL), LegalClauseChunker)
    assert isinstance(get_chunker(TenantIndustry.MEDICAL), SoapNoteChunker)


def test_legal_chunker_splits_by_clause_number():
    chunker = LegalClauseChunker()
    page_text = (
        "4.1 Confidentiality\nBoth parties shall keep terms confidential.\n"
        "4.2 Termination\nEither party may terminate with 30 days notice."
    )
    chunks = chunker.chunk([(4, page_text)])
    assert len(chunks) == 2
    assert chunks[0].section == "4.1"
    assert "Confidentiality" in chunks[0].text
    assert chunks[1].section == "4.2"
    assert "Termination" in chunks[1].text
    assert all(c.page == 4 for c in chunks)


def test_legal_chunker_falls_back_to_whole_page_without_clause_numbers():
    chunker = LegalClauseChunker()
    chunks = chunker.chunk([(1, "Just a preamble with no numbered clauses.")])
    assert len(chunks) == 1
    assert chunks[0].section is None


def test_soap_chunker_splits_by_soap_fields():
    chunker = SoapNoteChunker()
    page_text = (
        "Subjective:\nPatient reports headache.\n"
        "Objective:\nBP 130/85.\n"
        "Assessment:\nTension headache.\n"
        "Plan:\nOTC analgesics, follow up in 2 weeks."
    )
    chunks = chunker.chunk([(1, page_text)])
    assert [c.section for c in chunks] == ["Subjective", "Objective", "Assessment", "Plan"]
