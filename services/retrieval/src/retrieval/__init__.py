"""Retrieval service (blueprint 11.3). Imports no LLM client and no object store (blueprint 18 boundaries)."""

from __future__ import annotations

from lmqa_db import Database
from lmqa_models.settings import Settings
from lmqa_vectorstore import EmbeddingError, create_embedder
from retrieval.rerank import PassageScorer, Reranker, RerankError
from retrieval.service import ChunkOpener, RetrievalService, Retrieved


def create_retrieval(
    settings: Settings, db: Database, keys: ChunkOpener, reranker: PassageScorer | None = None
) -> RetrievalService:
    """`keys`: the process's field cipher (lmqa_keys.FieldCipher), which opens sealed chunk text. `reranker`: an
    injected scorer (the LLM re-ranker); None builds the local one RERANK_MODEL names, if any."""
    return RetrievalService(settings, db, create_embedder(settings), keys, reranker)


__all__ = [
    "ChunkOpener",
    "EmbeddingError",
    "PassageScorer",
    "RerankError",
    "Reranker",
    "RetrievalService",
    "Retrieved",
    "create_retrieval",
]
