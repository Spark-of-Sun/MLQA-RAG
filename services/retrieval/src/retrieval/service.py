"""Scoped multi-stage retrieval and the retrieval ledger (blueprint 11.3, 11.4, 9.4).

1. Embed the question and its alternative phrasings with each embedding model in use (one request per model);
   a model without quota is skipped and its passages are searched by text only.
2. Hybrid candidates: dense, stemmed full text and exact identifiers for every phrasing, fused by weighted
   reciprocal rank fusion, inside an RLS-bound transaction.
3. Fetch the best candidates' text under RLS; an ID that does not come back is dropped and counted (`not_visible`).
4. Re-rank them (a local cross-encoder, or the LLM chain with RERANK_MODEL=llm) and drop passages below the
   relevance threshold, so an irrelevant passage is never shown to the model (and a question nothing answers gets
   the refusal without an answer-model call).
5. Remove near-duplicates (repeated exhibits, copies of one clause), then admit whole passages in relevance order
   up to `top_k` and the token budget; never truncate a passage.
6. Neighbour expansion: the passages just before and after the best hits, in the same section, are added so an
   answer that runs across a passage boundary is still complete. They are read under RLS like everything else.
7. Give each kept passage a request-local alias (S1, S2, ...); the model never sees chunk IDs.

Every dropped candidate is recorded with its reason and score, so audit can show whether a relevant passage was
excluded and why (blueprint 11.4).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from lmqa_db import Database, Scope
from lmqa_models.contracts import feature_enabled
from lmqa_models.infra import load_infra_settings
from lmqa_models.principal import Principal
from lmqa_models.rag import Dropped, Source
from lmqa_models.settings import LLM_RERANK, Settings
from lmqa_vectorstore import (
    EmbeddingError,
    QuotaExhausted,
    SearchQuery,
    TextEmbedder,
    hybrid_candidates,
)
from lmqa_vectorstore.qdrant import VectorReader
from retrieval.rerank import PassageScorer, Reranker, RerankError
from retrieval.vector_search import qdrant_candidates, scope_of

log = logging.getLogger(__name__)

ALTERNATIVE_WEIGHT = 0.6  # a rewrite counts less than the question as asked
NEIGHBOUR_SEEDS = 3  # neighbours are added around this many of the best passages
DUPLICATE_JACCARD = 0.9
CARRY_MAX = 2

# Title, section and text are sealed with the document key (lmqa_keys, R-51.3) and opened after the RLS read.
_COLUMNS = (
    "c.id, c.org_id, c.workspace_id, c.document_id, c.version, c.ordinal, d.title_ct, c.section_ct,"
    " c.page_start, c.page_end, c.text_ct, c.text_sha256, c.token_count"
)


class ChunkOpener(Protocol):
    """The part of lmqa_keys.FieldCipher retrieval uses (retrieval imports no key provider, blueprint 18)."""

    def open_chunk_row(self, conn: Any, row: dict[str, Any]) -> dict[str, Any]: ...


def _open(keys: ChunkOpener, scope: Scope, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        item = keys.open_chunk_row(scope, dict(r))
        out.append({k: v for k, v in item.items() if not k.endswith("_ct")})
    return out


@dataclass
class Retrieved:
    sources: list[Source]
    dropped: list[Dropped]
    stats: dict[str, Any] = field(default_factory=dict)


def _shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + n]) for i in range(max(1, len(words) - n + 1))}


def _near_duplicate(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= DUPLICATE_JACCARD


class RetrievalService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        embedder: TextEmbedder,
        keys: ChunkOpener,
        reranker: PassageScorer | None = None,
    ) -> None:
        self._s = settings
        self._db = db
        self._embedder = embedder
        self._keys = keys
        self.reranker: PassageScorer | None = reranker
        if reranker is None and settings.rerank_model and settings.rerank_model != LLM_RERANK:
            self.reranker = Reranker(settings.rerank_model, settings.model_cache_dir)
        elif reranker is None and settings.rerank_model == LLM_RERANK:
            log.warning(
                "RERANK_MODEL=llm but no LLM re-ranker was provided; using the fused ranking"
            )
        self.vector_reader = None
        if feature_enabled("qdrant_vectors"):
            infra = load_infra_settings()
            # Read-only key: retrieval cannot write vectors (G5.1).
            self.vector_reader = VectorReader(infra.qdrant_url, infra.require("QDRANT_KEY_RO"))

    def warm(self) -> None:
        if self.reranker is not None:
            self.reranker.warm()

    def retrieve(  # noqa: C901, PLR0912, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        question: str,
        *,
        budget_tokens: int,
        alternatives: list[str] | None = None,
        carry_chunk_ids: list[str] | None = None,
    ) -> Retrieved:
        """Search for `question` (the standalone form) and its `alternatives`. `carry_chunk_ids` are the passages
        cited in the previous turn of the conversation: up to two keep a reserved place so a follow-up ("explain
        that") can still see them. They are re-read under RLS, so a revoked or deleted source is not carried."""
        m = p.membership
        assert m is not None and m.workspace_id is not None
        s = self._s
        timings: dict[str, int] = {}
        t0 = time.monotonic()
        phrasings = [question, *(alternatives or [])]
        with self._db.scoped(p.user_id) as scope:
            in_use = [
                r["embedding_model"]
                for r in scope.execute(
                    "select distinct embedding_model from chunks"
                    " where workspace_id = %s and embedding_model is not null",
                    [m.workspace_id],
                ).fetchall()
            ]
        # The question is embedded once per model the workspace's passages use. A model that is unavailable (daily
        # quota used up, provider down) is skipped: its passages are still found by the full-text and exact-term
        # channels, so a question is answered from fewer signals instead of failing.
        vectors_by_model: dict[str, list[list[float]]] = {}
        degraded: list[str] = []
        for model in sorted(
            in_use,
            key=lambda x: self._embedder.models.index(x) if x in self._embedder.models else 99,
        ):
            try:
                vectors_by_model[model] = self._embedder.embed_queries(phrasings, model)
            except EmbeddingError as exc:
                log.warning(
                    "question embedding with %s unavailable (%s); searching its passages by text",
                    model,
                    exc,
                )
                if isinstance(exc, QuotaExhausted):
                    self._embedder.mark_down(model)
                degraded.append(model)
        timings["embed_ms"] = _ms(t0)

        t1 = time.monotonic()
        queries = [
            SearchQuery(
                text,
                {mod: vecs[i] for mod, vecs in vectors_by_model.items()},
                1.0 if i == 0 else ALTERNATIVE_WEIGHT,
            )
            for i, text in enumerate(phrasings)
        ]
        pool_size = s.rerank_candidates if self.reranker else s.retrieval_top_k * 3
        with self._db.scoped(p.user_id) as scope:
            vscope = scope_of(scope) if self.vector_reader is not None else None
            if self.vector_reader is not None:
                if vscope is None:
                    fused = []
                else:
                    fused = qdrant_candidates(
                        self.vector_reader,
                        vscope,
                        queries,
                        prefetch=s.retrieval_prefetch,
                        cache_dir=s.model_cache_dir,
                    )
            else:
                fused = hybrid_candidates(
                    scope,
                    workspace_id=m.workspace_id,
                    queries=queries,
                    prefetch=s.retrieval_prefetch,
                )
            pool = fused[:pool_size]
            pool_ids = {cid for cid, _ in pool}
            carry = [cid for cid in dict.fromkeys(carry_chunk_ids or []) if cid not in pool_ids][
                :CARRY_MAX
            ]
            rows = self._rows(scope, [cid for cid, _ in pool] + carry) if pool or carry else {}
        timings["search_ms"] = _ms(t1)

        dropped: list[Dropped] = [
            Dropped(cid, "not_visible", score) for cid, score in pool if cid not in rows
        ]
        visible = [(cid, score) for cid, score in pool if cid in rows]
        carried = [cid for cid in carry if cid in rows]

        # Stage 2: re-ranker relevance. Ranking quality is not a safety boundary (the validator checks every
        # sentence), so if the re-ranker fails the fused order is used and the failure is reported.
        t2 = time.monotonic()
        rerank_state = "off"
        ranked: list[tuple[str, float]] = visible
        if self.reranker is not None and visible:
            try:
                probs = self.reranker.score(question, [_passage(rows[cid]) for cid, _ in visible])
                ranked = sorted(
                    zip([cid for cid, _ in visible], probs, strict=True),
                    key=lambda kv: (-kv[1], kv[0]),
                )
                rerank_state = "on"
            except RerankError as exc:
                log.warning("%s; using the fused ranking", exc)
                rerank_state = "failed"
        timings["rerank_ms"] = _ms(t2)

        if rerank_state == "on":
            passing = [(cid, sc) for cid, sc in ranked if sc >= s.rerank_min_score]
            dropped += [
                Dropped(cid, "below_threshold", sc) for cid, sc in ranked if sc < s.rerank_min_score
            ]
        else:
            passing = ranked

        # Carried passages keep their place even when the new question's wording scores them low.
        top_score = passing[0][1] if passing else 0.0
        reserved = [(cid, top_score) for cid in carried]
        candidates = (
            passing[: max(s.retrieval_top_k - len(reserved), 0)]
            + reserved
            + passing[s.retrieval_top_k :]
        )

        kept: list[tuple[str, float]] = []
        kept_shingles: list[set[tuple[str, ...]]] = []
        seen_sha: set[str] = set()
        used = 0
        for cid, score in candidates:
            row = rows[cid]
            sh = _shingles(row["text"])
            if row["text_sha256"] in seen_sha or any(_near_duplicate(sh, k) for k in kept_shingles):
                dropped.append(Dropped(cid, "duplicate", score))
            elif len(kept) >= s.retrieval_top_k:
                dropped.append(Dropped(cid, "below_top_k", score))
            elif used + row["token_count"] > budget_tokens:
                dropped.append(Dropped(cid, "token_budget", score))
            else:
                kept.append((cid, score))
                kept_shingles.append(sh)
                seen_sha.add(row["text_sha256"])
                used += row["token_count"]

        # Stage 3: neighbour expansion around the best passages, in document order.
        neighbours = 0
        order: list[tuple[str, float, bool]] = [(cid, sc, False) for cid, sc in kept]
        if s.retrieval_neighbors > 0 and kept and len(kept) < s.retrieval_top_k:
            with self._db.scoped(p.user_id) as scope:
                extra = self._neighbours(scope, [rows[cid] for cid, _ in kept[:NEIGHBOUR_SEEDS]])
            have = {cid for cid, _ in kept}
            expanded: list[tuple[str, float, bool]] = []
            for cid, score in kept:
                row = rows[cid]
                before, after = [], []
                for n in extra.get(cid, []):
                    nid = str(n["id"])
                    if (
                        nid in have
                        or n["text_sha256"] in seen_sha
                        or len(kept) + neighbours >= s.retrieval_top_k
                        or used + n["token_count"] > budget_tokens
                    ):
                        continue
                    rows[nid] = n
                    have.add(nid)
                    seen_sha.add(n["text_sha256"])
                    used += n["token_count"]
                    neighbours += 1
                    (before if n["ordinal"] < row["ordinal"] else after).append((nid, score, True))
                expanded += [*before, (cid, score, False), *after]
            order = expanded

        sources = [
            Source(
                chunk_id=cid,
                document_id=str(rows[cid]["document_id"]),
                document_title=rows[cid]["title"],
                section=rows[cid]["section"],
                page_start=rows[cid]["page_start"],
                page_end=rows[cid]["page_end"],
                text=rows[cid]["text"],
                sha256=rows[cid]["text_sha256"],
                token_count=rows[cid]["token_count"],
                score=round(score, 4),
                alias=f"S{i}",
            )
            for i, (cid, score, _) in enumerate(order, start=1)
        ]
        stats = {
            "queries": len(phrasings),
            "candidates": len(fused),
            "reranked": len(visible) if rerank_state == "on" else 0,
            "rerank": rerank_state,
            "rerank_model": self.reranker.model if self.reranker else None,
            "neighbours": neighbours,
            "kept": len(sources),
            "embedding_models": list(vectors_by_model),
            "embedding_unavailable": degraded,
            **timings,
        }
        return Retrieved(sources, dropped, stats)

    def _rows(self, scope: Scope, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
        rows = scope.execute(
            f"select {_COLUMNS} from chunks c join documents d on d.id = c.document_id"  # noqa: S608 - _COLUMNS is a module constant; values bound
            " where c.id = any(%s) and d.status = 'ready'",
            [chunk_ids],
        ).fetchall()
        return {str(r["id"]): r for r in _open(self._keys, scope, rows)}

    def _neighbours(
        self, scope: Scope, seeds: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """seed chunk id -> the passages within `retrieval_neighbors` of it in the same document and section."""
        if not seeds:
            return {}
        n = self._s.retrieval_neighbors
        rows = scope.execute(
            f"select {_COLUMNS}, s.ord as seed_ordinal from unnest(%s::uuid[], %s::int[]) as s(doc, ord)"  # noqa: S608 - _COLUMNS is a module constant; values bound
            " join chunks c on c.document_id = s.doc and c.ordinal between s.ord - %s and s.ord + %s"
            " and c.ordinal <> s.ord join documents d on d.id = c.document_id where d.status = 'ready'"
            " order by c.document_id, c.ordinal",
            [[r["document_id"] for r in seeds], [r["ordinal"] for r in seeds], n, n],
        ).fetchall()
        rows = _open(self._keys, scope, rows)
        by_position = {(str(r["document_id"]), r["ordinal"]): r for r in seeds}
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            seed = by_position.get((str(r["document_id"]), r["seed_ordinal"]))
            if seed is not None and (seed["section"] or None) == (r["section"] or None):
                out.setdefault(str(seed["id"]), []).append(r)
        return out

    def current_chunks(self, scope: Scope, chunk_ids: list[str]) -> dict[str, tuple[str, str]]:
        """chunk_id -> (text, sha256) as visible to the scope right now (V3 at release, side-panel recheck)."""
        if not chunk_ids:
            return {}
        rows = scope.execute(
            "select id, org_id, workspace_id, document_id, version, text_ct, section_ct, text_sha256 from chunks"
            " where id = any(%s)",
            [chunk_ids],
        ).fetchall()
        return {str(r["id"]): (r["text"], r["text_sha256"]) for r in _open(self._keys, scope, rows)}

    @staticmethod
    def record_ledger(scope: Scope, query_id: str, sources: list[Source]) -> None:
        with scope.cursor() as cur:
            cur.executemany(
                "insert into retrieval_records (query_id, alias, chunk_id, chunk_sha256, rank, score)"
                " values (%s, %s, %s, %s, %s, %s)",
                [
                    (query_id, s.alias, s.chunk_id, s.sha256, i, s.score)
                    for i, s in enumerate(sources, start=1)
                ],
            )


def _passage(row: dict[str, Any]) -> str:
    """What the re-ranker reads: the document and section give a passage its context, as a reader would see it."""
    head = " — ".join(x for x in (row["title"], row["section"]) if x)
    return f"{head}\n{row['text']}" if head else row["text"]


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
