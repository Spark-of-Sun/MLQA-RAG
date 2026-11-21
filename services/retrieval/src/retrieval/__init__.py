"""Retrieval service (blueprint 11.3). Imports no LLM client and no object store (blueprint 18 boundaries)."""

from __future__ import annotations

from lmqa_db import Database
from lmqa_models.settings import Settings
from lmqa_vectorstore import Embedder, EmbeddingError
from retrieval.service import RetrievalService


def create_retrieval(settings: Settings, db: Database) -> RetrievalService:
    return RetrievalService(settings, db, Embedder(settings))


__all__ = ["EmbeddingError", "RetrievalService", "create_retrieval"]
