"""Vectors: embedding (Gemini) and hybrid search (pgvector + PostgreSQL full text).

MVP deviation (blueprint 10.5, ADR 0004 fallback): vectors live in PostgreSQL with pgvector, so the same
row-level security that guards chunk text also guards vector search. Search functions take a `Scope`
(an RLS-bound transaction) and have no unfiltered variant.
"""

from lmqa_vectorstore.embeddings import Embedder, EmbeddingError, QuotaExhausted
from lmqa_vectorstore.search import SearchQuery, exact_terms, hybrid_candidates, vector_literal

__all__ = [
    "Embedder",
    "EmbeddingError",
    "QuotaExhausted",
    "SearchQuery",
    "exact_terms",
    "hybrid_candidates",
    "vector_literal",
]
