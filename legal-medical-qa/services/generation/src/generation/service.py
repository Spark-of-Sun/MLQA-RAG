"""The generation service (doc 4.2, 11.3 to 11.5): ledger in, a streamed answer out.

Flow for one request, in the caller's database context:

1. Read the retrieval ledger row for the request (the same user's own, DEF-63) and the chunks it
   names, decrypted under RLS. The Gateway never forwards chunk text.
2. If retrieval kept nothing, the answer is the canonical refusal and **no model call is made**.
3. Assemble the prompt inside the hard token budget (aliases only, delimited blocks).
4. Look up the scoped cache; on a hit stream the cached text, else call the model through the
   circuit breaker and cache the completed answer.

The answer stream is *unverified* text: only the validator may approve a sentence for release.
STATUS: written and type-checked; not exercised end to end here (needs a real LLM key).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import text

from generation.cache import AnswerCache, cache_key
from generation.llm import CircuitBreaker, LlmClient, guarded_stream
from generation.prompt import Assembled, ChunkInfo, PromptRegistry, assemble
from lmqa_keys import Aad, KeyService, decrypt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from generation.budget import TokenCounter
    from lmqa_db import Database, DbContext

CANONICAL_REFUSAL: Final = "The provided documents do not address this."


@dataclass(frozen=True, slots=True)
class Prepared:
    """Everything decided before any text is produced, also what audit records."""

    assembled: Assembled | None
    cache_key: str | None
    cached: str | None
    workspace_key: bytes | None
    refusal: bool


class GenerationService:
    """Holds the real components for one deployment."""

    def __init__(  # noqa: PLR0913, PLR0917 - the real components of the service
        self,
        db: Database,
        keys: KeyService,
        registry: PromptRegistry,
        counter: TokenCounter,
        llm: LlmClient,
        breaker: CircuitBreaker,
        cache: AnswerCache,
        *,
        max_output: int = 1_500,
        budget: int = 12_000,
    ) -> None:
        """Bind the components. ``db`` connects as ``svc_generation``."""
        self._db, self._keys, self._registry, self._counter = db, keys, registry, counter
        self._llm, self._breaker, self._cache = llm, breaker, cache
        self._max_output, self._budget = max_output, budget

    async def _load(
        self, ctx: DbContext, request_id: UUID
    ) -> tuple[str, list[ChunkInfo], list[tuple[str, int]], bytes]:
        async with self._db.scoped(ctx) as s:
            row = (
                await s.execute(
                    text("SELECT scope_hash, items FROM retrieval_records WHERE request_id = :r"),
                    {"r": request_id},
                )
            ).first()
            if row is None:
                return "", [], [], b""
            items = row[1] if isinstance(row[1], list) else json.loads(row[1])
            kept = [i for i in items if i.get("alias")]
            if not kept:
                return str(row[0]), [], [], b""
            ids = [UUID(i["chunk_id"]) for i in kept]
            rows = (
                await s.execute(
                    text(
                        "SELECT c.id, c.doc_id, c.doc_version, c.ordinal, c.text_ciphertext, "
                        "c.page_start, c.page_end,"
                        " c.section_path, d.title_ciphertext FROM chunks c JOIN documents d ON "
                        "d.id = c.doc_id"
                        " WHERE c.id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            ).all()
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
        by_id = {r[0]: r for r in rows}
        infos: list[ChunkInfo] = []
        for item in kept:
            r = by_id.get(UUID(item["chunk_id"]))
            blob = wrapped.get(r[1]) if r else None
            if r is None or blob is None:
                continue  # unreadable now: it is simply not offered to the model
            doc_key = KeyService.open_document_key(ws_key, bytes(blob), ctx.org, ctx.ws, r[1])
            body = decrypt(doc_key, bytes(r[4]), Aad(ctx.org, ctx.ws, r[1], r[2], r[3])).decode()
            title = decrypt(doc_key, bytes(r[8]), Aad(ctx.org, ctx.ws, r[1], 0)).decode()
            infos.append(
                ChunkInfo(item["alias"], body, int(item["rank"]), title, r[5], r[6], r[7] or "")
            )
        return str(row[0]), infos, [(i["chunk_id"], int(i["version"])) for i in kept], ws_key

    async def prepare(
        self, ctx: DbContext, request_id: UUID, question: str, *, use_cache: bool = True
    ) -> Prepared:
        """Resolve chunks, build the prompt within budget and consult the cache."""
        scope_hash, infos, chunk_set, ws_key = await self._load(ctx, request_id)
        if not infos:
            return Prepared(None, None, None, None, refusal=True)
        system, few_shot, _ = self._registry.load("answer_system", "v1")
        assembled = assemble(
            self._counter,
            system,
            few_shot,
            "v1",
            question,
            infos,
            budget=self._budget,
            max_output=self._max_output,
        )
        key = cache_key(
            ctx.org,
            ctx.ws,
            scope_hash,
            chunk_set,
            assembled.prompt_hash,
            self._llm.model_id,
            question,
        )
        cached = await self._cache.get(key, ws_key, ctx.org, ctx.ws) if use_cache else None
        return Prepared(assembled, key, cached, ws_key, refusal=False)

    async def stream(self, ctx: DbContext, prepared: Prepared) -> AsyncIterator[str]:
        """Yield unverified text deltas for a prepared request."""
        if prepared.refusal or prepared.assembled is None:
            yield CANONICAL_REFUSAL
            return
        if prepared.cached is not None:
            yield prepared.cached
            return
        parts: list[str] = []
        async for delta in guarded_stream(
            self._llm,
            self._breaker,
            prepared.assembled.system,
            prepared.assembled.user,
            max_tokens=self._max_output,
        ):
            parts.append(delta)
            yield delta
        if prepared.cache_key and prepared.workspace_key:
            await self._cache.put(
                prepared.cache_key, "".join(parts), prepared.workspace_key, ctx.org, ctx.ws
            )
