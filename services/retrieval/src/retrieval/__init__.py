"""Retrieval service (blueprint 11.3). Imports no LLM client and no object store (blueprint 18 boundaries)."""

from __future__ import annotations

from lmqa_db import Database
from lmqa_models.settings import Settings
from lmqa_vectorstore import Embedder, EmbeddingError
from retrieval.rerank import PassageScorer, Reranker, RerankError
from retrieval.service import RetrievalService, Retrieved


def create_retrieval(settings: Settings, db: Database, reranker: PassageScorer | None = None) -> RetrievalService:
    """`reranker`: an injected scorer (the LLM re-ranker); None builds the local one RERANK_MODEL names, if any."""
    return RetrievalService(settings, db, Embedder(settings), reranker)


__all__ = [
    "EmbeddingError",
    "PassageScorer",
    "RerankError",
    "Reranker",
    "RetrievalService",
    "Retrieved",
    "create_retrieval",
]
