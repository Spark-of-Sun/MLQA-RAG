from __future__ import annotations

from dataclasses import dataclass

from common.models import Chunk, ConfidentialityTier

from app.filters import apply_access_filter
from app.hybrid_search.sparse import sparse_search
from app.reranker.base import Reranker
from app.state import VectorSearchBackend


@dataclass
class RankedChunk:
    chunk: Chunk
    dense_score: float | None
    sparse_score: float | None
    rerank_score: float | None


def _fake_query_embedding(query: str, dimension: int = 32) -> list[float]:
    """Retrieval doesn't own an embedding model of its own — in production
    this calls the same embedding backend Ingestion uses (same model,
    different process) to embed the query text. For now this is a
    placeholder; wiring it to app.embedding (once shared) is TODO before
    QdrantVectorSearchBackend is used against real data.
    """
    import hashlib

    digest = hashlib.sha256(query.encode("utf-8")).digest()
    raw = (digest * ((dimension // len(digest)) + 1))[:dimension]
    return [b / 255.0 for b in raw]


def hybrid_search(
    *,
    query: str,
    tenant_id: str,
    matter_or_patient_id: str,
    confidentiality_tiers_allowed: list[ConfidentialityTier],
    vector_search: VectorSearchBackend,
    reranker: Reranker,
    top_k_dense: int = 40,
    top_k_sparse: int = 40,
    rerank_top_k: int = 8,
) -> tuple[list[RankedChunk], int]:
    """Dense (vector) + sparse (BM25) combination, metadata-filtered
    BEFORE ranking, then cross-encoder re-ranked — the full pipeline from
    docs/architecture.md §4. Returns (ranked_chunks, dropped_chunk_count).
    """
    query_vector = _fake_query_embedding(query)
    dense_pairs = vector_search.dense_search(query_vector, tenant_id, matter_or_patient_id, top_k_dense)
    dense_candidates = [chunk for chunk, _ in dense_pairs]
    dense_scores = {chunk.chunk_id: score for chunk, score in dense_pairs}

    # Metadata filter is applied before ranking, per docs/architecture.md §4 —
    # a user can never retrieve chunks outside their access grant.
    allowed_chunks, dropped_count = apply_access_filter(
        dense_candidates, tenant_id, matter_or_patient_id, confidentiality_tiers_allowed
    )

    sparse_scores = sparse_search(query, allowed_chunks, top_k_sparse)

    combined: list[RankedChunk] = []
    for chunk in allowed_chunks:
        combined.append(
            RankedChunk(
                chunk=chunk,
                dense_score=dense_scores.get(chunk.chunk_id),
                sparse_score=sparse_scores.get(chunk.chunk_id),
                rerank_score=None,
            )
        )

    reranked = reranker.rerank(query, combined, top_k=rerank_top_k)
    return reranked, dropped_count
