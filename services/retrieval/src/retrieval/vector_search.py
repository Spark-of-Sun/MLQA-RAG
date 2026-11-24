"""Qdrant candidate search for retrieval (blueprint 10.5, 11.3, G5.1, G5.4, G5.8, G5.9, G5.12).

The scope comes from PostgreSQL (`app_vector_scope()`), never from token claims. Each phrasing is searched with
dense and sparse vectors inside the scope filter; results are fused by weighted reciprocal rank. Every candidate is
then re-read under RLS by the caller (RetrievalService._rows), so the vector store narrows search but never
decides access: a candidate RLS does not return is counted as `not_visible` (stale index, G5.8). Qdrant down is a
503 with no fallback scan (G5.12).
"""

from __future__ import annotations

from typing import Any

from lmqa_db import Scope
from lmqa_models.errors import Unavailable
from lmqa_vectorstore.qdrant import VectorReader, VectorScope
from lmqa_vectorstore.search import SearchQuery
from lmqa_vectorstore.sparse import encode_query

RRF_K = 60


def scope_of(scope: Scope) -> VectorScope | None:
    row = scope.execute("select app_vector_scope() as s").fetchone()
    data: dict[str, Any] | None = row["s"] if row else None
    if not data:
        return None
    return VectorScope(
        org_id=str(data["org_id"]),
        workspace_id=str(data["workspace_id"]),
        user_id=str(data["user_id"]),
        role=str(data["role"]),
        walled_matters=frozenset(str(m) for m in data["walled"]),
        grants=tuple((str(m), int(t)) for m, t in data["grants"]),
        emergency=tuple((str(m), int(t)) for m, t in data["emergency"]),
        break_glass=bool(data["break_glass"]),
    )


def qdrant_candidates(
    reader: VectorReader,
    vscope: VectorScope,
    queries: list[SearchQuery],
    *,
    prefetch: int,
    cache_dir: Any = None,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    try:
        for q in queries:
            dense = next(iter(q.vectors.values()), None) if q.vectors else None
            sparse = encode_query(q.text, cache_dir)
            for rank, (chunk_id, _) in enumerate(
                reader.hybrid(vscope, dense=dense, sparse=sparse, limit=prefetch)
            ):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + q.weight / (RRF_K + rank + 1)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise Unavailable("Search is unavailable; no answer was released.") from exc
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
