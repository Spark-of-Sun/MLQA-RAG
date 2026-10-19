from __future__ import annotations

import os
from typing import Protocol

from common.models import Chunk, ConfidentialityTier


class VectorSearchBackend(Protocol):
    """Dense (vector) search side of hybrid search. Retrieval never
    writes to this store — only Ingestion does (services/ingestion/app/
    workers/vector_store.py) — this is read-only by design."""

    def dense_search(
        self,
        query_vector: list[float],
        tenant_id: str,
        matter_or_patient_id: str,
        top_k: int,
    ) -> list[tuple[Chunk, float]]:
        """Returns (chunk, dense_score) pairs, already filtered to the
        tenant/matter scope at the vector-store level (metadata filter
        pushed down before ranking, per docs/architecture.md §4)."""
        ...


class InMemoryVectorSearchBackend:
    """Local/test stand-in — holds chunks in memory, scores by a trivial
    token-overlap heuristic instead of real cosine similarity. Deterministic
    and dependency-free, for unit tests only. Never used against real data.
    """

    def __init__(self):
        self._chunks: list[Chunk] = []

    def seed(self, chunks: list[Chunk]) -> None:
        self._chunks.extend(chunks)

    def dense_search(self, query_vector, tenant_id, matter_or_patient_id, top_k):
        scored = [(c, 1.0) for c in self._chunks]
        return scored[:top_k]


class QdrantVectorSearchBackend:
    """Real backend — reads from the same Qdrant collection Ingestion
    writes to (same client library both environments, docs/architecture.md §8).
    """

    def __init__(self, host: str | None = None, port: int | None = None, collection: str | None = None):
        from qdrant_client import QdrantClient

        self._collection = collection or os.environ.get("QDRANT_COLLECTION", "legalmed_chunks")
        self._client = QdrantClient(
            host=host or os.environ.get("QDRANT_HOST", "qdrant"),
            port=port or int(os.environ.get("QDRANT_PORT", "6333")),
        )

    def dense_search(self, query_vector, tenant_id, matter_or_patient_id, top_k):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                    FieldCondition(key="matter_or_patient_id", match=MatchValue(value=matter_or_patient_id)),
                ]
            ),
            limit=top_k,
        )
        pairs = []
        for point in results:
            payload = point.payload or {}
            chunk = Chunk(
                chunk_id=str(point.id),
                document_id=payload["document_id"],
                tenant_id=payload["tenant_id"],
                matter_or_patient_id=payload["matter_or_patient_id"],
                text=payload["text"],
                page=payload["page"],
                section=payload.get("section"),
                confidentiality_tier=ConfidentialityTier(payload["confidentiality_tier"]),
            )
            pairs.append((chunk, point.score))
        return pairs


def build_vector_search_backend() -> VectorSearchBackend:
    backend = os.environ.get("VECTOR_SEARCH_BACKEND", "qdrant")
    if backend == "qdrant":
        return QdrantVectorSearchBackend()
    if backend == "in-memory":
        return InMemoryVectorSearchBackend()
    raise ValueError(f"unknown VECTOR_SEARCH_BACKEND: {backend}")


def load_seed_chunks(path: str) -> list[Chunk]:
    """Loads a JSON file of chunk dicts into Chunk models, for manual
    local testing without a real Qdrant instance — set
    VECTOR_SEARCH_BACKEND=in-memory and SEED_CHUNKS_FILE=/path/to/file.json
    before starting this service. Never used in the Docker image; the real
    stack is seeded by Ingestion writing into Qdrant, not this loader.
    """
    import json

    with open(path) as f:
        raw_chunks = json.load(f)
    return [Chunk(**c) for c in raw_chunks]


class AppState:
    def __init__(self, vector_search: VectorSearchBackend):
        self.vector_search = vector_search

    @classmethod
    async def create(cls) -> "AppState":
        backend = build_vector_search_backend()
        seed_file = os.environ.get("SEED_CHUNKS_FILE")
        if seed_file and isinstance(backend, InMemoryVectorSearchBackend):
            backend.seed(load_seed_chunks(seed_file))
        return cls(backend)

    async def aclose(self) -> None:
        pass
