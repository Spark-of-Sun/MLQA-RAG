from __future__ import annotations

from common.models import Chunk


def sparse_search(query: str, chunks: list[Chunk], top_k: int) -> dict[str, float]:
    """BM25 keyword search — legal/medical queries often include exact
    terms (statute numbers, drug names, dosages) pure semantic search can
    miss, per docs/architecture.md §4. Returns {chunk_id: bm25_score} for
    the top_k scoring chunks only.

    rank_bm25 is a small pure-Python dependency (no heavy ML deps), so
    there's no fake/real split here the way there is for embeddings/
    reranking — this runs the same way in tests and in production.
    """
    if not chunks:
        return {}

    from rank_bm25 import BM25Okapi

    tokenized_corpus = [c.text.lower().split() for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())

    scored_pairs = sorted(zip(chunks, scores), key=lambda p: p[1], reverse=True)
    return {chunk.chunk_id: float(score) for chunk, score in scored_pairs[:top_k]}
