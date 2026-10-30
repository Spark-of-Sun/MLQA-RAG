"""The validator's view of PostgreSQL: the retrieval ledger and the current chunk text (doc 9.4).

Everything is read under RLS as ``svc_validator`` in the *requesting user's* context, so the
ledger row must belong to that user (DEF-63) and a chunk the user can no longer read, or that was
crypto-erased, comes back as ``None`` and fails V3. Chunk text never travels through the Gateway.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from citation_validator.checks import ChunkView, LedgerEntry
from lmqa_keys import Aad, KeyService, decrypt

if TYPE_CHECKING:
    from lmqa_db import Database, DbContext


class ValidatorStore:
    """Reads the ledger and chunks for one request."""

    def __init__(self, db: Database, keys: KeyService) -> None:
        """Bind a ``svc_validator`` connection and the key service."""
        self._db, self._keys = db, keys

    async def ledger(self, ctx: DbContext, request_id: UUID) -> dict[str, LedgerEntry]:
        """The kept entries of a retrieval, by alias. Empty if the request is not this user's."""
        async with self._db.scoped(ctx) as s:
            row = (
                await s.execute(
                    text("SELECT items FROM retrieval_records WHERE request_id = :r"),
                    {"r": request_id},
                )
            ).scalar()
        if row is None:
            return {}
        items = row if isinstance(row, list) else json.loads(row)
        return {
            i["alias"]: LedgerEntry(i["alias"], i["chunk_id"], int(i["version"]), i["sha256"])
            for i in items
            if i.get("alias")
        }

    async def chunks(
        self, ctx: DbContext, ledger: dict[str, LedgerEntry]
    ) -> dict[str, ChunkView | None]:
        """Current decrypted chunks for the ledger aliases; ``None`` where unreadable now."""
        if not ledger:
            return {}
        ids = [UUID(e.chunk_id) for e in ledger.values()]
        async with self._db.scoped(ctx) as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT c.id, c.doc_id, c.doc_version, c.ordinal, c.text_ciphertext, "
                        "c.page_start, c.page_end,"
                        " c.section_path, c.clause_no, d.title_ciphertext FROM chunks c JOIN "
                        "documents d ON d.id = c.doc_id"
                        " WHERE c.id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            ).all()
            if not rows:
                return dict.fromkeys(ledger)
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
        by_id: dict[UUID, ChunkView] = {}
        aliases = {UUID(e.chunk_id): a for a, e in ledger.items()}
        for r in rows:
            blob = wrapped.get(r[1])
            if blob is None:
                continue
            doc_key = KeyService.open_document_key(ws_key, bytes(blob), ctx.org, ctx.ws, r[1])
            body = decrypt(doc_key, bytes(r[4]), Aad(ctx.org, ctx.ws, r[1], r[2], r[3])).decode()
            title = decrypt(doc_key, bytes(r[9]), Aad(ctx.org, ctx.ws, r[1], 0)).decode()
            by_id[r[0]] = ChunkView(aliases[r[0]], body, title, r[2], r[5], r[6], r[7] or "", r[8])
        return {alias: by_id.get(UUID(e.chunk_id)) for alias, e in ledger.items()}
