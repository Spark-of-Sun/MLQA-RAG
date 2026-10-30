"""The generation HTTP API.

``POST /internal/v1/answer`` streams unverified text as server-sent events.

The request ID comes from the verified context token, never from the body, so a caller can only
generate from its own retrieval ledger.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from generation.service import GenerationService
from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims

Claims = Annotated[ContextClaims, Depends(context_claims())]


class AnswerIn(BaseModel):
    """The user's question."""

    question: str = Field(min_length=1, max_length=2000)
    use_cache: bool = True
    """False on a regeneration attempt, so a failed answer is never served again from the cache."""


def _event(name: str, data: dict[str, object]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def create_app(service: GenerationService, verifier: ContextVerifier) -> FastAPI:
    """Build the app around a constructed service and this service's own token verifier."""
    app = FastAPI(title="generation", docs_url=None, redoc_url=None)
    app.state.verifier = verifier

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/v1/answer")
    async def answer(body: AnswerIn, claims: Claims) -> StreamingResponse:
        ctx = claims.db_context()
        prepared = await service.prepare(
            ctx, claims.request_id, body.question, use_cache=body.use_cache
        )

        async def events() -> AsyncIterator[bytes]:
            meta = prepared.assembled
            yield _event(
                "meta",
                {
                    "prompt_hash": meta.prompt_hash if meta else None,
                    "prompt_version": meta.prompt_version if meta else None,
                    "kept": list(meta.kept) if meta else [],
                    "dropped": list(meta.dropped) if meta else [],
                    "cached": prepared.cached is not None,
                    "refusal": prepared.refusal,
                },
            )
            async for delta in service.stream(ctx, prepared):
                yield _event("delta", {"text": delta})
            yield _event("done", {})

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    return app
