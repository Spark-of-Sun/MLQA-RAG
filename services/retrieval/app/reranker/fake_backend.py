from __future__ import annotations

from dataclasses import replace


class FakeReranker:
    """Deterministic cross-encoder stand-in for local unit tests — scores
    each candidate by word overlap between query and chunk text (a cheap,
    dependency-free proxy for semantic relevance). Never used in the
    Docker image — see CrossEncoderReranker for the real bge-reranker model.
    """

    def rerank(self, query, candidates, top_k):
        query_tokens = set(query.lower().split())
        scored = []
        for candidate in candidates:
            chunk_tokens = set(candidate.chunk.text.lower().split())
            overlap = len(query_tokens & chunk_tokens)
            score = overlap / (len(query_tokens) or 1)
            scored.append(replace(candidate, rerank_score=score))
        scored.sort(key=lambda c: c.rerank_score, reverse=True)
        return scored[:top_k]
