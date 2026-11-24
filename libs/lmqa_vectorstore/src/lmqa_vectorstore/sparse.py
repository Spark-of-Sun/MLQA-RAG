"""Sparse lexical vectors for hybrid search in Qdrant (blueprint 11.3): BM25 term weights computed locally with
fastembed's `Qdrant/bm25` model (IDF is applied by the collection's sparse-vector modifier). No text leaves the
machine for this step. Loaded once per process."""

from __future__ import annotations

import threading
from pathlib import Path

_MODEL = "Qdrant/bm25"
_lock = threading.Lock()
_encoder: object | None = None


def _get(cache_dir: Path | None) -> object:
    global _encoder
    with _lock:
        if _encoder is None:
            from fastembed import SparseTextEmbedding

            _encoder = SparseTextEmbedding(_MODEL, cache_dir=str(cache_dir) if cache_dir else None)
        return _encoder


def encode_documents(
    texts: list[str], cache_dir: Path | None = None
) -> list[tuple[list[int], list[float]]]:
    enc = _get(cache_dir)
    return [(e.indices.tolist(), e.values.tolist()) for e in enc.embed(texts)]  # type: ignore[attr-defined]


def encode_query(text: str, cache_dir: Path | None = None) -> tuple[list[int], list[float]]:
    enc = _get(cache_dir)
    e = next(iter(enc.query_embed(text)))  # type: ignore[attr-defined]
    return e.indices.tolist(), e.values.tolist()
