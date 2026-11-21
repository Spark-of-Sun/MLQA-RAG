"""The ingestion pipeline (doc 11.1): upload completion through to a searchable, encrypted document.

Every database step runs in the document *owner's* context (the signed job envelope in production),
so PostgreSQL RLS stays the authority even for background work. The document state machine is
enforced by database triggers: an illegal transition fails in the database. Plaintext exists only
in memory and in the quarantine prefix; everything stored is encrypted under a random per-document
key that is wrapped by the workspace key, so deleting that key shreds the document on its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import text

from ingestion.chunker import ChunkConfig, Tokenizer, chunk_document
from ingestion.parsers import UnsupportedFormatError, parse
from lmqa_audit import AuditEvent, AuditWriter
from lmqa_keys import Aad, KeyService, encrypt
from lmqa_vectorstore import ChunkPoint

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ingestion.embedder import Embedder
    from ingestion.model import ChunkDraft
    from ingestion.scanner import Scanner
    from lmqa_db import Database, DbContext
    from lmqa_objectstore import ObjectStore
    from lmqa_vectorstore import VectorWriter

EMBED_BATCH: Final = 32
_CTX = {"admin": "admin", "tenant": "tenant"}


class DocumentHeldError(RuntimeError):
    """The document is under legal hold or retention and cannot be deleted."""


@dataclass(frozen=True, slots=True)
class Components:
    """Everything the pipeline depends on, all real."""

    db: Database
    keys: KeyService
    objects: ObjectStore
    vectors: VectorWriter
    embedder: Embedder
    scanner: Scanner
    tokenizer: Tokenizer
    chunk_config: ChunkConfig
    audit: AuditWriter = field(default_factory=AuditWriter)


@dataclass(frozen=True, slots=True)
class Upload:
    """The ticket returned when an upload starts."""

    doc_id: UUID
    version: int = 1


@dataclass(frozen=True, slots=True)
class IngestResult:
    """What happened to a document."""

    doc_id: UUID
    status: str
    chunks: int = 0
    reason: str | None = None
    ocr_pages: tuple[int, ...] = ()
    structure: str = "detected"


@dataclass(frozen=True, slots=True)
class _Keys:
    cmk_id: str
    version: int
    workspace_key: bytes


class IngestionPipeline:
    """Orchestrates the ten steps of section 11.1."""

    def __init__(self, c: Components) -> None:
        """Bind the components."""
        self.c = c

    # ------------------------------------------------------------------ key material
    async def _keys(self, session: AsyncSession, ctx: DbContext) -> _Keys:
        cmk = (
            await session.execute(
                text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": ctx.org_id}
            )
        ).scalar_one()
        row = (
            await session.execute(
                text(
                    "SELECT version, wrapped_key FROM workspace_keys WHERE workspace_id = :w AND state = 'active'"
                    " ORDER BY version DESC LIMIT 1"
                ),
                {"w": ctx.workspace_id},
            )
        ).one()
        key = await self.c.keys.workspace_key(
            str(cmk), ctx.org_id, ctx.workspace_id, int(row[0]), bytes(row[1])
        )  # type: ignore[arg-type]
        return _Keys(str(cmk), int(row[0]), key)

    async def _doc_key(
        self, session: AsyncSession, ctx: DbContext, doc_id: UUID, ws_key: bytes
    ) -> bytes:
        wrapped = (
            await session.execute(
                text("SELECT wrapped_key FROM doc_keys WHERE doc_id = :d"), {"d": doc_id}
            )
        ).scalar_one()
        return KeyService.open_document_key(
            ws_key,
            None if wrapped is None else bytes(wrapped),
            ctx.org_id,
            ctx.workspace_id,
            doc_id,
        )  # type: ignore[arg-type]

    async def _status(
        self, session: AsyncSession, doc_id: UUID, status: str, reason: str | None = None
    ) -> None:
        await session.execute(
            text("UPDATE documents SET status = :s, failure_reason = :r WHERE id = :d"),
            {"s": status, "r": reason, "d": doc_id},
        )

    async def _audit(
        self,
        session: AsyncSession,
        ctx: DbContext,
        action: str,
        doc_id: UUID,
        outcome: str = "ok",
        reason: str | None = None,
    ) -> None:
        await self.c.audit.append(
            session,
            ctx.org_id,
            ctx.workspace_id,  # type: ignore[arg-type]
            AuditEvent(
                action,
                outcome,
                "workspace",
                ctx.user_id,
                ctx.role.value,
                f"document:{doc_id}",
                reason,
            ),
        )

    # ------------------------------------------------------------------ step 1: upload init
    async def create_upload(
        self, ctx: DbContext, title: str, visibility: str, matter_id: UUID | None, tier: int
    ) -> Upload:
        """Create the document row (``uploading``) with an encrypted title and its random key."""
        doc_id = uuid.uuid7()
        async with self.c.db.scoped(ctx) as s:
            keys = await self._keys(s, ctx)
            doc_key, wrapped = KeyService.new_document_key(
                keys.workspace_key, ctx.org_id, ctx.workspace_id, doc_id
            )  # type: ignore[arg-type]
            title_ct = encrypt(
                doc_key, title.encode(), Aad(ctx.org_id, ctx.workspace_id, doc_id, 0)
            )  # type: ignore[arg-type]
            await s.execute(
                text(
                    "INSERT INTO documents (id, org_id, workspace_id, owner_user_id, matter_id, title_ciphertext,"
                    " visibility, confidentiality_tier) VALUES (:d, :o, :w, :u, :m, :t, :v, :tier)"
                ),
                {
                    "d": doc_id,
                    "o": ctx.org_id,
                    "w": ctx.workspace_id,
                    "u": ctx.user_id,
                    "m": matter_id,
                    "t": title_ct,
                    "v": visibility,
                    "tier": tier,
                },
            )
            await s.execute(
                text(
                    "INSERT INTO doc_keys (doc_id, org_id, workspace_id, wrapped_key, key_version)"
                    " VALUES (:d, :o, :w, :k, :v)"
                ),
                {
                    "d": doc_id,
                    "o": ctx.org_id,
                    "w": ctx.workspace_id,
                    "k": wrapped,
                    "v": keys.version,
                },
            )
            await self._audit(s, ctx, "document.upload_started", doc_id)
        return Upload(doc_id)

    # ------------------------------------------------------------------ steps 2 to 10
    async def _fail(
        self, ctx: DbContext, doc_id: UUID, reason: str, *, delete_upload: bool = True
    ) -> IngestResult:
        if delete_upload:
            await self.c.objects.delete_quarantine(ctx.org_id, ctx.workspace_id, doc_id)  # type: ignore[arg-type]
        async with self.c.db.scoped(ctx) as s:
            await self._status(s, doc_id, "failed", reason)
            await self._audit(s, ctx, "document.failed", doc_id, "fail", reason)
        return IngestResult(doc_id, "failed", reason=reason)

    async def complete_upload(
        self, ctx: DbContext, doc_id: UUID, declared_type: str, expected_sha256: str
    ) -> IngestResult:
        """Verify the checksum, scan, parse, chunk, encrypt, store, embed and index."""
        org, ws = ctx.org_id, ctx.workspace_id
        data, actual = await self.c.objects.read_quarantine(org, ws, doc_id)  # type: ignore[arg-type]
        if actual != expected_sha256.lower():
            return await self._fail(ctx, doc_id, "checksum_mismatch")
        async with self.c.db.scoped(ctx) as s:
            await self._status(s, doc_id, "scanning")
        verdict = await self.c.scanner.scan(data)
        if not verdict.clean:
            return await self._fail(ctx, doc_id, verdict.reason or "scan_failed")
        async with self.c.db.scoped(ctx) as s:
            await self._status(s, doc_id, "parsing")
        try:
            parsed = await asyncio.to_thread(parse, data, declared_type)
            drafts = await asyncio.to_thread(
                chunk_document, parsed, self.c.tokenizer, self.c.chunk_config
            )
        except UnsupportedFormatError:
            return await self._fail(ctx, doc_id, "unsupported_format")
        except Exception:  # a parser crash isolates to this document
            return await self._fail(ctx, doc_id, "parser_error")
        ocr_pages = tuple(p.number for p in parsed.pages if p.extraction == "none")
        if not drafts and not ocr_pages:
            return await self._fail(ctx, doc_id, "no_text")
        chunk_ids = await self._store(
            ctx, doc_id, data, drafts, parsed.domain_hint == "medical", actual
        )
        if ocr_pages:  # nothing is searchable until a human reviews the pages without a text layer
            async with self.c.db.scoped(ctx) as s:
                await self._status(s, doc_id, "ocr_review")
                await self._audit(s, ctx, "document.ocr_review", doc_id)
            return IngestResult(
                doc_id, "ocr_review", len(drafts), ocr_pages=ocr_pages, structure=parsed.structure
            )
        await self._index(ctx, doc_id, drafts, chunk_ids)
        return IngestResult(doc_id, "indexed", len(drafts), structure=parsed.structure)

    async def _store(
        self,
        ctx: DbContext,
        doc_id: UUID,
        original: bytes,
        drafts: list[ChunkDraft],
        phi: bool,
        sha256: str,
    ) -> list[UUID]:
        org, ws = ctx.org_id, ctx.workspace_id
        assert org is not None and ws is not None  # noqa: S101
        async with self.c.db.scoped(ctx) as s:
            keys = await self._keys(s, ctx)
            doc_key = await self._doc_key(s, ctx, doc_id, keys.workspace_key)
            doc = (
                await s.execute(
                    text(
                        "SELECT matter_id, visibility, confidentiality_tier, owner_user_id FROM documents WHERE id = :d"
                    ),
                    {"d": doc_id},
                )
            ).one()
            rows, ids = [], []
            for d in drafts:
                chunk_id = uuid.uuid7()
                ids.append(chunk_id)
                rows.append(
                    {
                        "id": chunk_id,
                        "o": org,
                        "w": ws,
                        "d": doc_id,
                        "n": d.ordinal,
                        "u": doc[3],
                        "m": doc[0],
                        "v": doc[1],
                        "t": doc[2],
                        "kind": d.kind,
                        "sp": d.section_path,
                        "cn": d.clause_no,
                        "h": d.heading,
                        "ps": d.page_start,
                        "pe": d.page_end,
                        "spans": json.dumps(
                            [{"page": x.page, "start": x.start, "end": x.end} for x in d.spans]
                        ),
                        "ct": encrypt(doc_key, d.text.encode(), Aad(org, ws, doc_id, 1, d.ordinal)),
                        "sha": hashlib.sha256(d.text.encode()).hexdigest(),
                        "tok": d.token_count,
                        "phi": phi,
                    }
                )
            if rows:
                await s.execute(
                    text(
                        "INSERT INTO chunks (id, org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id,"
                        " matter_id, visibility, confidentiality_tier, kind, section_path, clause_no, heading,"
                        " page_start, page_end, spans, text_ciphertext, text_sha256, token_count, contains_phi)"
                        " VALUES (:id, :o, :w, :d, 1, :n, :u, :m, :v, :t, :kind, :sp, :cn, :h, :ps, :pe,"
                        " CAST(:spans AS jsonb), :ct, :sha, :tok, :phi)"
                    ),
                    rows,
                )
            object_key = await self.c.objects.put_encrypted(doc_key, org, ws, doc_id, 1, [original])
            await s.execute(
                text(
                    "INSERT INTO document_versions (doc_id, org_id, workspace_id, version, object_key, object_sha256,"
                    " embedding_version) VALUES (:d, :o, :w, 1, :k, :h, :e)"
                ),
                {
                    "d": doc_id,
                    "o": org,
                    "w": ws,
                    "k": object_key,
                    "h": sha256,
                    "e": self.c.embedder.config.version,
                },
            )
        await self.c.objects.delete_quarantine(
            org, ws, doc_id
        )  # the plaintext upload is gone once encrypted
        return ids

    async def _index(
        self, ctx: DbContext, doc_id: UUID, drafts: list[ChunkDraft], chunk_ids: list[UUID]
    ) -> None:
        org, ws = ctx.org_id, ctx.workspace_id
        assert org is not None and ws is not None  # noqa: S101
        async with self.c.db.scoped(ctx) as s:
            await self._status(s, doc_id, "indexing")
            doc = (
                await s.execute(
                    text(
                        "SELECT matter_id, visibility, confidentiality_tier, owner_user_id FROM documents WHERE id = :d"
                    ),
                    {"d": doc_id},
                )
            ).one()
        points: list[ChunkPoint] = []
        for start in range(0, len(drafts), EMBED_BATCH):
            batch = drafts[start : start + EMBED_BATCH]
            vectors = await self.c.embedder.embed_documents([d.text for d in batch])
            for offset, (d, (dense, sparse)) in enumerate(zip(batch, vectors, strict=True)):
                points.append(
                    ChunkPoint(
                        chunk_ids[start + offset],
                        dense,
                        sparse,
                        org,
                        ws,
                        doc_id,
                        1,
                        doc[3],
                        doc[0],
                        doc[1],
                        int(doc[2]),
                    )
                )
        try:
            await self.c.vectors.upsert(points)
        except Exception:
            async with self.c.db.scoped(ctx) as s:
                await self._status(s, doc_id, "failed", "index_failed")
            raise
        async with self.c.db.scoped(ctx) as s:
            await s.execute(
                text(
                    "UPDATE document_versions SET index_state = 'in_sync' WHERE doc_id = :d AND version = 1"
                ),
                {"d": doc_id},
            )
            await self._status(s, doc_id, "indexed")
            await self._audit(s, ctx, "document.indexed", doc_id)

    # ------------------------------------------------------------------ access changes (outbox)
    async def change_access(
        self, ctx: DbContext, doc_id: UUID, *, visibility: str, matter_id: UUID | None, tier: int
    ) -> None:
        """Change visibility, matter or tier. Postgres changes first; the vector index follows via the outbox."""
        async with self.c.db.scoped(ctx) as s:
            await s.execute(
                text(
                    "UPDATE documents SET visibility = :v, matter_id = :m, confidentiality_tier = :t WHERE id = :d"
                ),
                {"v": visibility, "m": matter_id, "t": tier, "d": doc_id},
            )
            await s.execute(
                text(
                    "UPDATE chunks SET visibility = :v, matter_id = :m, confidentiality_tier = :t,"
                    " payload_version = payload_version + 1 WHERE doc_id = :d"
                ),
                {"v": visibility, "m": matter_id, "t": tier, "d": doc_id},
            )
            await s.execute(
                text("UPDATE document_versions SET index_state = 'stale' WHERE doc_id = :d"),
                {"d": doc_id},
            )
            await s.execute(
                text(
                    "INSERT INTO index_outbox (org_id, workspace_id, doc_id, doc_version, operation)"
                    " VALUES (:o, :w, :d, 1, 'set_payload')"
                ),
                {"o": ctx.org_id, "w": ctx.workspace_id, "d": doc_id},
            )
            await self._audit(s, ctx, "document.access_changed", doc_id)

    async def apply_outbox(self, ctx: DbContext, doc_id: UUID) -> int:
        """Apply pending re-index rows for a document (the indexer worker). Returns how many were applied."""
        org, ws = ctx.org_id, ctx.workspace_id
        assert org is not None and ws is not None  # noqa: S101
        async with self.c.db.scoped(ctx) as s:
            pending = (
                await s.execute(
                    text(
                        "SELECT id FROM index_outbox WHERE doc_id = :d AND state = 'pending' ORDER BY id"
                    ),
                    {"d": doc_id},
                )
            ).all()
            if not pending:
                return 0
            doc = (
                await s.execute(
                    text(
                        "SELECT matter_id, visibility, confidentiality_tier, owner_user_id FROM documents WHERE id = :d"
                    ),
                    {"d": doc_id},
                )
            ).one()
            version = int(
                (
                    await s.execute(
                        text("SELECT max(payload_version) FROM chunks WHERE doc_id = :d"),
                        {"d": doc_id},
                    )
                ).scalar_one()
            )
        fields: dict[str, str | int | bool] = {
            "visibility": doc[1],
            "tier": int(doc[2]),
            "payload_version": version,
        }
        fields["matter_id"] = str(doc[0]) if doc[0] else ""
        await self.c.vectors.set_access_payload(org, ws, doc_id, fields)
        async with self.c.db.scoped(ctx) as s:
            await s.execute(
                text(
                    "UPDATE index_outbox SET state = 'done' WHERE doc_id = :d AND state = 'pending'"
                ),
                {"d": doc_id},
            )
            await s.execute(
                text("UPDATE document_versions SET index_state = 'in_sync' WHERE doc_id = :d"),
                {"d": doc_id},
            )
        return len(pending)

    # ------------------------------------------------------------------ deletion (crypto-erase)
    async def delete_document(self, ctx: DbContext, doc_id: UUID) -> None:
        """Destroy the key first (atomic with the row changes), then remove vectors and objects."""
        org, ws = ctx.org_id, ctx.workspace_id
        assert org is not None and ws is not None  # noqa: S101
        async with self.c.db.scoped(ctx) as s:
            try:
                await self._status(s, doc_id, "deleting")
            except Exception as exc:
                if "legal hold" in str(exc):
                    raise DocumentHeldError(str(doc_id)) from exc
                raise
            await s.execute(
                text(
                    "UPDATE doc_keys SET wrapped_key = NULL, state = 'destroyed' WHERE doc_id = :d"
                ),
                {"d": doc_id},
            )
            await s.execute(text("DELETE FROM chunks WHERE doc_id = :d"), {"d": doc_id})
            await s.execute(
                text(
                    "INSERT INTO deletion_tombstones (scope, target_id, org_id, approver_refs)"
                    " VALUES ('document', :d, :o, CAST(:r AS jsonb))"
                ),
                {"d": doc_id, "o": org, "r": json.dumps([str(ctx.user_id)])},
            )
        await self.c.vectors.delete_document(org, ws, doc_id)
        await self.c.objects.delete_document(org, ws, doc_id)
        async with self.c.db.scoped(ctx) as s:
            await self._status(s, doc_id, "deleted")
            await self._audit(s, ctx, "document.deleted", doc_id)
