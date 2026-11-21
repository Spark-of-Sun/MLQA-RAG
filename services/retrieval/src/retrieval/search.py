"""Retrieval (doc 11.3, 10.5, 9.4): scoped hybrid search with PostgreSQL as the final authority.

Steps for one request, all inside the caller's database context:

1. Resolve the scope from the database (``app_scope()``): grants, walls, emergency matters and the
   break-glass state. It is resolved on every request, so a wall created a moment ago applies now.
2. Build the Qdrant filter from that scope and run the hybrid query. Qdrant returns chunk IDs only.
3. Fetch the candidates' text from PostgreSQL **under RLS** and decrypt. Any ID Postgres does not
   return is dropped and counted: it means a stale index or a filter bug.
4. Re-rank, keep at most ``keep`` chunks at or above the threshold, record the rest as dropped.
5. Write the retrieval ledger row, which generation and the validator read; chunk text never
   travels through the Gateway.

If Qdrant is down the request fails (503); there is no fallback scan of PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from uuid import UUID

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from sqlalchemy import text

from lmqa_keys import Aad, KeyService, decrypt
from lmqa_vectorstore import MAX_INLINE_MATTERS, SparseVec, VectorReader, VectorScope

if TYPE_CHECKING:
    from lmqa_db import Database, DbContext

DEFAULT_DENSE: Final = "BAAI/bge-small-en-v1.5"
DEFAULT_SPARSE: Final = "Qdrant/bm25"
DEFAULT_RERANKER: Final = "Xenova/ms-marco-MiniLM-L-6-v2"
OVERFETCH_LIMIT: Final = 500
SEARCH_LIMIT: Final = 100
KEEP: Final = 12
# UNCALIBRATED placeholder: the real threshold comes from the Stage 5 calibration on labelled data.
DEFAULT_THRESHOLD: Final = -8.0


class RetrievalUnavailableError(RuntimeError):
    """The vector store failed. The caller answers 503; nothing falls back to a database scan."""


class NoAccessError(PermissionError):
    """The principal is not active, or no safe filter exists. The caller answers 403."""


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One chunk handed to generation. ``alias`` is request-local; the model never sees real IDs."""

    chunk_id: UUID
    doc_id: UUID
    doc_version: int
    ordinal: int
    alias: str
    text: str
    text_sha256: str
    page_start: int
    page_end: int
    section_path: str
    clause_no: str | None
    heading: str | None
    kind: str
    rank: int
    score: float


@dataclass(slots=True)
class RetrievalResult:
    """What a retrieval produced and what it dropped, with the reasons."""

    request_id: UUID
    chunks: list[RetrievedChunk]
    candidates: int = 0
    dropped: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    mismatches: int = 0
    overfetch: bool = False


@dataclass(frozen=True, slots=True)
class _Row:
    """A chunk fetched from PostgreSQL and decrypted."""

    id: UUID
    doc_id: UUID
    doc_version: int
    ordinal: int
    text: str
    sha: str
    ps: int
    pe: int
    sp: str | None
    cn: str | None
    h: str | None
    kind: str


class QueryModels:
    """Query-side embedding and the cross-encoder, loaded once."""

    def __init__(
        self,
        dense: str = DEFAULT_DENSE,
        sparse: str = DEFAULT_SPARSE,
        reranker: str = DEFAULT_RERANKER,
    ) -> None:
        """Load the models (downloaded on first use). Names match the ingestion embedder."""
        self._dense, self._sparse = TextEmbedding(dense), SparseTextEmbedding(sparse)
        self._rerank = TextCrossEncoder(reranker)

    def embed(self, query: str) -> tuple[list[float], SparseVec]:
        """Dense and sparse query vectors."""
        dense = next(iter(self._dense.query_embed(query))).tolist()
        sparse = next(iter(self._sparse.query_embed(query)))
        return dense, SparseVec(sparse.indices.tolist(), sparse.values.tolist())

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Cross-encoder relevance scores, deterministic for identical input."""
        return [float(x) for x in self._rerank.rerank(query, passages, batch_size=4)]


class Retriever:
    """Runs one retrieval. One instance serves the whole service."""

    def __init__(  # noqa: PLR0913 - the real components plus two tuning values
        self,
        db: Database,
        keys: KeyService,
        vectors: VectorReader,
        models: QueryModels,
        *,
        keep: int = KEEP,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        """Bind the real components. ``db`` connects as ``svc_retrieval``."""
        self._db, self._keys, self._vectors, self._models = db, keys, vectors, models
        self._keep, self._threshold = keep, threshold
        self.mismatch_total = 0

    async def scope(self, ctx: DbContext, narrow_to: frozenset[UUID] | None = None) -> VectorScope:
        """Resolve the caller's vector scope from the database."""
        async with self._db.scoped(ctx) as s:
            raw = (await s.execute(text("SELECT app_scope()"))).scalar_one()
        data = raw if isinstance(raw, dict) else json.loads(raw)
        if not data.get("active") or data.get("role") not in {"admin", "tenant"}:
            msg = "the principal is not active in an active workspace"
            raise NoAccessError(msg)
        return VectorScope(
            org_id=ctx.org,
            workspace_id=ctx.ws,
            user_id=ctx.user,
            role=data["role"],
            grants={UUID(m): int(t) for m, t in data["grants"].items()},
            walled=frozenset(UUID(m) for m in data["walls"]),
            emergency_matters=frozenset(UUID(m) for m in data["emergency"]),
            admin_private_read=bool(data["admin_private_read"]),
            narrow_to=narrow_to,
        )

    async def retrieve(
        self,
        ctx: DbContext,
        question: str,
        *,
        narrow_to: frozenset[UUID] | None = None,
        request_id: UUID | None = None,
    ) -> RetrievalResult:
        """Search, cross-check, re-rank, record. Raises ``RetrievalUnavailableError`` on failure."""
        scope = await self.scope(ctx, narrow_to)
        dense, sparse = await asyncio.to_thread(self._models.embed, question)
        try:
            hits, overfetch = await self._vectors.search(
                scope,
                dense,
                sparse,
                OVERFETCH_LIMIT if len(scope.grants) > MAX_INLINE_MATTERS else SEARCH_LIMIT,
            )
        except PermissionError:
            raise
        except Exception as exc:
            msg = "vector search failed"
            raise RetrievalUnavailableError(msg) from exc
        result = RetrievalResult(
            request_id or uuid.uuid7(), [], candidates=len(hits), overfetch=overfetch
        )
        rows = await self._fetch(ctx, [h.chunk_id for h in hits])
        returned = {r.id for r in rows}
        for hit in hits:
            if hit.chunk_id not in returned:  # Postgres refused it: stale index or a filter bug
                result.mismatches += 1
                result.dropped.append({"chunk_id": str(hit.chunk_id), "reason": "postgres_refused"})
        self.mismatch_total += result.mismatches
        if rows:
            scores = await asyncio.to_thread(self._models.score, question, [r.text for r in rows])
            ranked = sorted(zip(rows, scores, strict=True), key=lambda p: (-p[1], str(p[0].id)))
            for rank, (row, score) in enumerate(ranked, start=1):
                if score < self._threshold:
                    result.dropped.append(
                        {"chunk_id": str(row.id), "reason": "below_threshold", "score": score}
                    )
                elif len(result.chunks) >= self._keep:
                    result.dropped.append(
                        {"chunk_id": str(row.id), "reason": "over_limit", "score": score}
                    )
                else:
                    result.chunks.append(
                        RetrievedChunk(
                            row.id,
                            row.doc_id,
                            row.doc_version,
                            row.ordinal,
                            f"chunk_{len(result.chunks) + 1}",
                            row.text,
                            row.sha,
                            row.ps,
                            row.pe,
                            row.sp or "",
                            row.cn,
                            row.h,
                            row.kind,
                            rank,
                            score,
                        )
                    )
        await self._ledger(ctx, scope, result)
        return result

    async def _fetch(self, ctx: DbContext, ids: list[UUID]) -> list[_Row]:
        if not ids:
            return []
        async with self._db.scoped(ctx) as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT id, doc_id, doc_version, ordinal, text_ciphertext, text_sha256, "
                        "page_start, page_end,"
                        " section_path, clause_no, heading, kind FROM chunks WHERE id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            ).all()
            if not rows:
                return []
            cmk = (
                await s.execute(
                    text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": ctx.org}
                )
            ).scalar_one()
            wk = (
                await s.execute(
                    text(
                        "SELECT version, wrapped_key FROM workspace_keys WHERE workspace_id = :w "
                        "AND state = 'active'"
                        " ORDER BY version DESC LIMIT 1"
                    ),
                    {"w": ctx.ws},
                )
            ).one()
            wrapped = {
                r[0]: r[1]
                for r in (
                    await s.execute(
                        text("SELECT doc_id, wrapped_key FROM doc_keys WHERE doc_id = ANY(:d)"),
                        {"d": list({r[1] for r in rows})},
                    )
                ).all()
            }
        ws_key = await self._keys.workspace_key(str(cmk), ctx.org, ctx.ws, int(wk[0]), bytes(wk[1]))
        out: list[_Row] = []
        for r in rows:
            blob = wrapped.get(r[1])
            if blob is None:
                continue  # a crypto-erased document: its text can never be returned
            doc_key = KeyService.open_document_key(ws_key, bytes(blob), ctx.org, ctx.ws, r[1])
            plain = decrypt(doc_key, bytes(r[4]), Aad(ctx.org, ctx.ws, r[1], r[2], r[3])).decode()
            out.append(
                _Row(r[0], r[1], r[2], r[3], plain, r[5], r[6], r[7], r[8], r[9], r[10], r[11])
            )
        return out

    async def _ledger(self, ctx: DbContext, scope: VectorScope, result: RetrievalResult) -> None:
        """Write the retrieval record (insert-only for this role)."""
        scope_hash = f"{len(scope.grants)}:{len(scope.walled)}:{len(scope.emergency_matters)}"
        items = [
            {
                "chunk_id": str(c.chunk_id),
                "version": c.doc_version,
                "sha256": c.text_sha256,
                "alias": c.alias,
                "rank": c.rank,
                "score": c.score,
                "dropped": None,
            }
            for c in result.chunks
        ]
        items += [{**d, "alias": None, "dropped": d["reason"]} for d in result.dropped]
        async with self._db.scoped(ctx) as s:
            await s.execute(
                text(
                    "INSERT INTO retrieval_records (org_id, workspace_id, request_id, user_id, "
                    "scope_hash, items)"
                    " VALUES (:o, :w, :r, :u, :h, CAST(:i AS jsonb))"
                ),
                {
                    "o": ctx.org,
                    "w": ctx.ws,
                    "r": result.request_id,
                    "u": ctx.user,
                    "h": scope_hash,
                    "i": json.dumps(items),
                },
            )
