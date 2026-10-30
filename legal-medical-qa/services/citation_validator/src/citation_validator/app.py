"""The validator HTTP API (doc 15.9): ``validate-answer`` (buffered) and ``validate-stream``.

Both endpoints validate against the request ID inside the verified context token, never one the
client supplies, so a caller cannot validate another request's ledger.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from citation_validator.service import ValidatorService
from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims, ws_context_claims

Claims = Annotated[ContextClaims, Depends(context_claims())]
WsClaims = Annotated[ContextClaims, Depends(ws_context_claims())]


class AnswerIn(BaseModel):
    """The whole answer for buffered validation."""

    answer: str


def create_app(service: ValidatorService, verifier: ContextVerifier) -> FastAPI:
    """Build the app around a constructed service and this service's own token verifier."""
    app = FastAPI(title="citation-validator", docs_url=None, redoc_url=None)
    app.state.verifier = verifier

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/v1/validate-answer")
    async def validate_answer(body: AnswerIn, claims: Claims) -> dict[str, object]:
        verdicts = await service.validate_answer(
            claims.db_context(), claims.request_id, body.answer
        )
        return {
            "verdicts": [v.to_json() for v in verdicts],
            "all_failed": bool(verdicts)
            and not any(v.payload["passed"] and not v.payload["refusal"] for v in verdicts),
        }

    @app.websocket("/internal/v1/validate-stream")
    async def validate_stream(websocket: WebSocket, claims: WsClaims) -> None:
        """Full duplex: ``{"delta": ...}`` frames in, ``{"verdict": ...}`` frames out, then done."""
        await websocket.accept()

        async def deltas() -> AsyncIterator[str]:
            while True:
                frame = json.loads(await websocket.receive_text())
                if frame.get("end"):
                    return
                yield str(frame["delta"])

        try:
            async for verdict in service.validate_stream(
                claims.db_context(), claims.request_id, deltas()
            ):
                await websocket.send_json({"verdict": verdict.to_json()})
            await websocket.send_json({"done": True})
        except WebSocketDisconnect:
            return
        await websocket.close()

    return app
