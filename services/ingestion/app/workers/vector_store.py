
from __future__ import annotations

import os
from typing import Protocol

from common.models import Chunk


class VectorStore(Protocol):
    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def delete_document(self, document_id: str) -> None: ...


class InMemoryVectorStore:
    """Local/test stand-in — no real Qdrant connection needed. Keeps
    chunks+vectors in a dict keyed by chunk_id. Only ever constructed
    explicitly by unit tests — never chosen automatically by a factory,
    since silently falling back to an in-memory store in production would
    be a correctness bug, not a convenience.
    """

    def __init__(self):
        self._store: dict[str, tuple[Chunk, list[float]]] = {}

    def upsert_chunks(self, chunks, vectors):
        for chunk, vector in zip(chunks, vectors):
            self._store[chunk.chunk_id] = (chunk, vector)

    def delete_document(self, document_id):
        to_delete = [cid for cid, (chunk, _) in self._store.items() if chunk.document_id == document_id]
        for cid in to_delete:
            del self._store[cid]

    def count(self) -> int:
        return len(self._store)

    def all_chunks(self):
        return [chunk for chunk, _vector in self._store.values()]


class QdrantVectorStore:
    """Real backend — single-node Qdrant container locally, managed
    Qdrant/Weaviate in production (same client library both environments,
    per docs/architecture.md §8).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection: str | None = None,
        vector_size: int = 32,
    ):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._collection = collection or os.environ.get("QDRANT_COLLECTION", "legalmed_chunks")
        self._client = QdrantClient(
            host=host or os.environ.get("QDRANT_HOST", "qdrant"),
            port=port or int(os.environ.get("QDRANT_PORT", "6333")),
        )
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def upsert_chunks(self, chunks, vectors):
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(
                id=chunk.chunk_id,
                vector=vector,
                payload={
                    "document_id": chunk.document_id,
                    "tenant_id": chunk.tenant_id,
                    "matter_or_patient_id": chunk.matter_or_patient_id,
                    "confidentiality_tier": chunk.confidentiality_tier.value,
                    "page": chunk.page,
                    "section": chunk.section,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def delete_document(self, document_id):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]),
        )
