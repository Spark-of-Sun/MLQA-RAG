"""Hybrid candidate search: dense (pgvector cosine) + sparse (full text), fused by reciprocal rank fusion.

Both queries run inside the caller's `Scope`, so row-level security decides visibility. The explicit
workspace filter is defence in depth and helps the planner (blueprint 10.5: every filter carries the scope).
"""

from __future__ import annotations

from lmqa_db import Scope

RRF_K = 60


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def hybrid_candidates(
    scope: Scope, *, workspace_id: str, text: str, vector: list[float] | None, prefetch: int = 40
) -> list[tuple[str, float]]:
    """Return (chunk_id, fused score), best first. Ties break on chunk id, so results are deterministic."""
    scores: dict[str, float] = {}
    if vector is not None:
        scope.execute("select set_config('hnsw.ef_search', '100', true)")
        scope.execute("select set_config('hnsw.iterative_scan', 'strict_order', true)")
        dense = scope.execute(
            "select id from chunks where workspace_id = %s and embedding is not null"
            " order by embedding <=> %s::vector limit %s",
            [workspace_id, vector_literal(vector), prefetch],
        ).fetchall()
        for rank, row in enumerate(dense, start=1):
            key = str(row["id"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    # OR the stemmed terms: a natural-language question rarely has every word in one chunk.
    sparse = scope.execute(
        "select c.id from chunks c,"
        " lateral (select nullif(replace(plainto_tsquery('english', %s)::text, '&', '|'), '')::tsquery as q) s"
        " where c.workspace_id = %s and s.q is not null and c.tsv @@ s.q"
        " order by ts_rank_cd(c.tsv, s.q) desc, c.id limit %s",
        [text, workspace_id, prefetch],
    ).fetchall()
    for rank, row in enumerate(sparse, start=1):
        key = str(row["id"])
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
