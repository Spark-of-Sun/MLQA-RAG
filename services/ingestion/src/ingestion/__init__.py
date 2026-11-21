"""Ingestion service (blueprint 11.1)."""

from __future__ import annotations

from ingestion.documents import DocumentService
from ingestion.pipeline import Ingestor
from lmqa_db import Database
from lmqa_models.settings import Settings
from lmqa_objectstore import ObjectStore
from lmqa_vectorstore import Embedder


def create_ingestion(settings: Settings, db: Database, *, workers: int = 2) -> tuple[DocumentService, Ingestor]:
    """Build the service with its own object store and embedder (the gateway never holds either)."""
    store = ObjectStore(settings.data_dir / "objects")
    ingestor = Ingestor(db, store, Embedder(settings), workers=workers)
    return DocumentService(settings, db, store, ingestor), ingestor


__all__ = ["DocumentService", "Ingestor", "create_ingestion"]
