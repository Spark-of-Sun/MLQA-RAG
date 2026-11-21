"""Embedding with real models (doc 4.5, 11.1 step 9, 11.3).

Dense vectors from a sentence-embedding model and sparse BM25 weights for exact terms (statute
numbers, drug names, dosages), which dense search alone misses. Both run on CPU through ONNX
(fastembed), self-hosted, so no document text leaves the boundary. The model names are
configuration: the MVP defaults are small so they run anywhere; the production candidates
(``bge-m3``, ``bge-reranker-v2-m3``) are chosen by the Stage 4/5 bake-off.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastembed import SparseTextEmbedding, TextEmbedding

from lmqa_vectorstore import SparseVec

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_DENSE: Final = "BAAI/bge-small-en-v1.5"
DEFAULT_SPARSE: Final = "Qdrant/bm25"


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    """Which models, and the sequence limit that bounds chunk size."""

    dense_model: str = DEFAULT_DENSE
    sparse_model: str = DEFAULT_SPARSE
    max_sequence: int = 512
    batch_size: int = 8  # sequences per inference call; memory grows with batch x length

    @property
    def version(self) -> str:
        """Recorded per document version so a re-embed migration can swap collections."""
        return f"{self.dense_model}+{self.sparse_model}"


class Embedder:
    """Loads both models once and embeds batches off the event loop."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        """Load the dense and sparse models (downloaded on first use)."""
        self.config = config or EmbeddingConfig()
        self._dense = TextEmbedding(self.config.dense_model)
        self._sparse = SparseTextEmbedding(self.config.sparse_model)
        self.dimension = len(next(iter(self._dense.embed(["dimension probe"]))))

    def embed_documents_sync(self, texts: Sequence[str]) -> list[tuple[list[float], SparseVec]]:
        """Dense and sparse vectors for chunk texts."""
        dense = [
            v.tolist() for v in self._dense.embed(list(texts), batch_size=self.config.batch_size)
        ]
        sparse = [
            SparseVec(s.indices.tolist(), s.values.tolist())
            for s in self._sparse.embed(list(texts), batch_size=self.config.batch_size)
        ]
        return list(zip(dense, sparse, strict=True))

    def embed_query_sync(self, query: str) -> tuple[list[float], SparseVec]:
        """Dense and sparse vectors for a question (queries use the models' query side)."""
        dense = next(iter(self._dense.query_embed(query))).tolist()
        sparse = next(iter(self._sparse.query_embed(query)))
        return dense, SparseVec(sparse.indices.tolist(), sparse.values.tolist())

    async def embed_documents(self, texts: Sequence[str]) -> list[tuple[list[float], SparseVec]]:
        """Async wrapper: model inference runs in a worker thread."""
        return await asyncio.to_thread(self.embed_documents_sync, texts)

    async def embed_query(self, query: str) -> tuple[list[float], SparseVec]:
        """Async wrapper for a single query."""
        return await asyncio.to_thread(self.embed_query_sync, query)
