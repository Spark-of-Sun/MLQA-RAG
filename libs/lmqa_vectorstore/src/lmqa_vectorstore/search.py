"""Hybrid candidate search, fused by weighted reciprocal rank fusion (blueprint 11.3 step 2).

Three channels per query, each a ranked list:
  dense   pgvector cosine similarity on the passage embedding (meaning, paraphrase), once per embedding model in use:
          a question is compared only with passages embedded by the same model
  text    the stemmed 'english' full-text index, any stemmed term (wording)
  exact   the unstemmed 'simple' index, only for identifiers in the query: numbers, dosages, section and statute
          references, codes, quoted phrases and proper names (the terms stemming and embeddings both blur)

Several phrasings of the same question can be searched at once (query expansion); each carries a weight, so the
question as asked counts more than a rewrite. Every query runs inside the caller's `Scope`, so row-level security
decides visibility; the explicit workspace filter is defence in depth and helps the planner (blueprint 10.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lmqa_db import Scope

RRF_K = 60

# Identifier-like tokens: anything with a digit (10 mg, 164.312(a)(2), 2024, EX-10.2, §3), all-caps words of two or
# more letters (HIPAA, ACE, FDA), and capitalised words that are not the first word of the question (Metoprolol).
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-/()§]*")
_QUOTED = re.compile(r"\"([^\"]{3,120})\"|“([^”]{3,120})”")
_COMMON_CAPS = frozenset({"I", "A", "THE", "AND", "OR", "OF", "IN", "ON", "TO", "IS", "WHAT", "WHEN", "WHO", "HOW"})


@dataclass(frozen=True)
class SearchQuery:
    text: str
    vectors: dict[str, list[float]]  # embedding model -> the query's vector; empty: lexical channels only
    weight: float = 1.0


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def exact_terms(text: str) -> list[str]:
    """Identifiers worth matching literally. Empty for an ordinary prose question."""
    terms: list[str] = [next(g for g in m.groups() if g) for m in _QUOTED.finditer(text)]
    words = _TOKEN.findall(_QUOTED.sub(" ", text))
    for i, w in enumerate(words):
        core = w.strip(".-/()")
        if not core:
            continue
        has_digit = any(ch.isdigit() for ch in core)
        acronym = core.isupper() and len(core) >= 2 and core not in _COMMON_CAPS
        proper_name = i > 0 and core[0].isupper() and len(core) >= 4
        if has_digit or acronym or proper_name:
            terms.append(core)
    return list(dict.fromkeys(terms))[:12]


def hybrid_candidates(
    scope: Scope, *, workspace_id: str, queries: list[SearchQuery], prefetch: int = 100
) -> list[tuple[str, float]]:
    """Return (chunk_id, fused score), best first. Ties break on chunk id, so results are deterministic."""
    scores: dict[str, float] = {}

    def fuse(rows: list[dict[str, object]], weight: float) -> None:
        for rank, row in enumerate(rows, start=1):
            key = str(row["id"])
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank)

    if any(q.vectors for q in queries):
        scope.execute("select set_config('hnsw.ef_search', %s, true)", [str(max(100, prefetch * 2))])
        scope.execute("select set_config('hnsw.iterative_scan', 'strict_order', true)")
    for q in queries:
        for model, vector in q.vectors.items():
            fuse(
                scope.execute(
                    "select id from chunks where workspace_id = %s and embedding_model = %s"
                    " order by embedding <=> %s::vector limit %s",
                    [workspace_id, model, vector_literal(vector), prefetch],
                ).fetchall(),
                q.weight,
            )
        # OR the stemmed terms: a natural-language question rarely has every word in one passage.
        fuse(
            scope.execute(
                "select c.id from chunks c,"
                " lateral (select nullif(replace(plainto_tsquery('english', %s)::text, '&', '|'), '')::tsquery as q) s"
                " where c.workspace_id = %s and s.q is not null and c.tsv @@ s.q"
                " order by ts_rank_cd(c.tsv, s.q, 32) desc, c.id limit %s",
                [q.text, workspace_id, prefetch],
            ).fetchall(),
            q.weight,
        )
        if terms := exact_terms(q.text):
            # Each term is matched as a phrase of its words; any term may match. Passages matching more of the
            # identifiers rank higher.
            fuse(
                scope.execute(
                    "select c.id from chunks c,"
                    " lateral (select nullif(string_agg('(' || nullif(phraseto_tsquery('simple', t)::text, '')"
                    " || ')', ' | '), '')::tsquery as q from unnest(%s::text[]) t) s"
                    " where c.workspace_id = %s and s.q is not null and c.tsv_simple @@ s.q"
                    " order by ts_rank_cd(c.tsv_simple, s.q, 32) desc, c.id limit %s",
                    [terms, workspace_id, prefetch],
                ).fetchall(),
                q.weight,
            )
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
