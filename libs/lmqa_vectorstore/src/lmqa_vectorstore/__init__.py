"""Vectors: embedding (Gemini, or a local model with EMBEDDING_PROVIDER=local) and hybrid search
(pgvector + PostgreSQL full text).

MVP deviation (blueprint 10.5, ADR 0004 fallback): vectors live in PostgreSQL with pgvector, so the same
row-level security that guards chunk text also guards vector search. Search functions take a `Scope`
(an RLS-bound transaction) and have no unfiltered variant.
"""

from lmqa_vectorstore.embeddings import Embedder, EmbeddingError, QuotaExhausted
from lmqa_vectorstore.local_embeddings import LocalEmbedder, TextEmbedder, create_embedder
from lmqa_vectorstore.search import SearchQuery, exact_terms, hybrid_candidates, vector_literal

__all__ = [
    "Embedder",
    "EmbeddingError",
    "LocalEmbedder",
    "QuotaExhausted",
    "SearchQuery",
    "TextEmbedder",
    "create_embedder",
    "exact_terms",
    "hybrid_candidates",
    "vector_literal",
]
