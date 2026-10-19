from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.hybrid_search.pipeline import RankedChunk


class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: list[RankedChunk], top_k: int
    ) -> list[RankedChunk]:
        """Scores each candidate's rerank_score in place (returns new
        RankedChunk instances) and returns the top_k, descending by
        rerank_score. This re-ranked, trimmed set is what flows
        downstream to Generation — a major token-optimization lever
        per docs/architecture.md §4."""
        ...
