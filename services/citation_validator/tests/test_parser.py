from __future__ import annotations

from app.parser import parse_citations


def test_parse_single_citation():
    results = parse_citations("The term is 12 months [c1].")
    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert "12 months" in results[0].sentence
    assert "[c1]" not in results[0].sentence


def test_parse_multiple_sentences_each_with_own_citation():
    text = "Term is 12 months [c1]. Notice period is 30 days [c2]."
    results = parse_citations(text)
    assert [r.chunk_id for r in results] == ["c1", "c2"]


def test_parse_sentence_with_multiple_citations():
    results = parse_citations("This is supported by two sources [c1][c2].")
    assert [r.chunk_id for r in results] == ["c1", "c2"]
    assert all("two sources" in r.sentence for r in results)


def test_parse_no_citation_returns_empty():
    assert parse_citations("This sentence has no citation at all.") == []
