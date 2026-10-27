"""lmqa_vectorstore: Vector operations and tenant isolation filters."""

from __future__ import annotations

from lmqa_vectorstore.client import VectorStoreClient
from lmqa_vectorstore.embeddings import compute_deterministic_embedding, cosine_similarity
from lmqa_vectorstore.filter import VectorFilterBuilder
from lmqa_vectorstore.local import LocalVectorStoreClient
from lmqa_vectorstore.models import VectorPoint, VectorQuery, VectorSearchResult
from lmqa_vectorstore.qdrant import QdrantVectorStoreClient

__all__ = [
    "LocalVectorStoreClient",
    "QdrantVectorStoreClient",
    "VectorFilterBuilder",
    "VectorPoint",
    "VectorQuery",
    "VectorSearchResult",
    "VectorStoreClient",
    "compute_deterministic_embedding",
    "cosine_similarity",
]
