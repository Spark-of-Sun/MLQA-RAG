from __future__ import annotations

from app.hybrid_search.pipeline import RankedChunk
from app.reranker import FakeReranker
from tests.conftest import _make_chunk


def test_fake_reranker_orders_by_word_overlap():
    reranker = FakeReranker()
    candidates = [
        RankedChunk(chunk=_make_chunk("c1", "the cat sat on the mat"), dense_score=None, sparse_score=None, rerank_score=None),
        RankedChunk(chunk=_make_chunk("c2", "completely unrelated text about dogs"), dense_score=None, sparse_score=None, rerank_score=None),
    ]
    results = reranker.rerank("cat mat", candidates, top_k=2)
    assert results[0].chunk.chunk_id == "c1"
    assert results[0].rerank_score > results[1].rerank_score


def test_fake_reranker_respects_top_k():
    reranker = FakeReranker()
    candidates = [
        RankedChunk(chunk=_make_chunk(f"c{i}", f"text number {i}"), dense_score=None, sparse_score=None, rerank_score=None)
        for i in range(5)
    ]
    results = reranker.rerank("text", candidates, top_k=2)
    assert len(results) == 2
