from __future__ import annotations

from app.hybrid_search.sparse import sparse_search
from tests.conftest import _make_chunk


def test_sparse_search_ranks_keyword_match_higher():
    chunks = [
        _make_chunk("c1", "statute 12345 governs this termination clause"),
        _make_chunk("c2", "general confidentiality obligations apply"),
    ]
    scores = sparse_search("statute 12345", chunks, top_k=2)
    assert scores["c1"] > scores.get("c2", 0.0)


def test_sparse_search_empty_chunks_returns_empty_dict():
    assert sparse_search("anything", [], top_k=5) == {}
