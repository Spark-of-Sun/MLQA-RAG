"""Scoped hybrid retrieval and the retrieval ledger (blueprint 11.3, 11.4, 9.4).

1. Embed the question.
2. Hybrid candidates (dense + full text, fused) inside an RLS-bound transaction.
3. Fetch chunk text under RLS; an ID that does not come back is dropped and counted (`not_visible`).
4. Admit whole chunks in rank order up to `top_k` and the token budget; never truncate a chunk.
5. Give each kept chunk a request-local alias (S1, S2, ...); the model never sees chunk IDs.
"""

from __future__ import annotations

from lmqa_db import Database, Scope
from lmqa_models.principal import Principal
from lmqa_models.rag import Dropped, Source
from lmqa_models.settings import Settings
from lmqa_vectorstore import Embedder, hybrid_candidates


class RetrievalService:
    def __init__(self, settings: Settings, db: Database, embedder: Embedder) -> None:
        self._s = settings
        self._db = db
        self._embedder = embedder

    def retrieve(self, p: Principal, question: str, *, budget_tokens: int) -> tuple[list[Source], list[Dropped]]:
        m = p.membership
        assert m is not None and m.workspace_id is not None
        vector = self._embedder.embed_query(question)
        top_k = self._s.retrieval_top_k
        with self._db.scoped(p.user_id) as scope:
            ranked = hybrid_candidates(scope, workspace_id=m.workspace_id, text=question, vector=vector)[: top_k * 3]
            if not ranked:
                return [], []
            rows = scope.execute(
                "select c.id, c.document_id, d.title, c.section, c.page_start, c.page_end, c.text, c.text_sha256,"
                " c.token_count from chunks c join documents d on d.id = c.document_id"
                " where c.id = any(%s) and d.status = 'ready'",
                [[cid for cid, _ in ranked]],
            ).fetchall()
        by_id = {str(r["id"]): r for r in rows}
        kept: list[Source] = []
        dropped: list[Dropped] = []
        used = 0
        for cid, score in ranked:
            row = by_id.get(cid)
            if row is None:
                dropped.append(Dropped(cid, "not_visible", score))
            elif len(kept) >= top_k:
                dropped.append(Dropped(cid, "below_top_k", score))
            elif used + row["token_count"] > budget_tokens:
                dropped.append(Dropped(cid, "token_budget", score))
            else:
                used += row["token_count"]
                kept.append(
                    Source(
                        chunk_id=cid,
                        document_id=str(row["document_id"]),
                        document_title=row["title"],
                        section=row["section"],
                        page_start=row["page_start"],
                        page_end=row["page_end"],
                        text=row["text"],
                        sha256=row["text_sha256"],
                        token_count=row["token_count"],
                        score=score,
                        alias=f"S{len(kept) + 1}",
                    )
                )
        return kept, dropped

    @staticmethod
    def current_chunks(scope: Scope, chunk_ids: list[str]) -> dict[str, tuple[str, str]]:
        """chunk_id -> (text, sha256) as visible to the scope right now (V3 at release, side-panel recheck)."""
        if not chunk_ids:
            return {}
        rows = scope.execute("select id, text, text_sha256 from chunks where id = any(%s)", [chunk_ids]).fetchall()
        return {str(r["id"]): (r["text"], r["text_sha256"]) for r in rows}

    @staticmethod
    def record_ledger(scope: Scope, query_id: str, sources: list[Source]) -> None:
        with scope.cursor() as cur:
            cur.executemany(
                "insert into retrieval_records (query_id, alias, chunk_id, chunk_sha256, rank, score)"
                " values (%s, %s, %s, %s, %s, %s)",
                [(query_id, s.alias, s.chunk_id, s.sha256, i, s.score) for i, s in enumerate(sources, start=1)],
            )
