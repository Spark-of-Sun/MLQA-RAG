from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from common.auth.jwt import SessionClaims
from common.logging import get_logger
from common.models import Action, AuditEvent, Citation, ValidationOutcome

from app.auth.dependencies import get_current_claims
from app.middleware.tenant_scope import enforce_scope
from app.schemas.requests import QueryRequest
from app.state import AppState, ServiceUnavailableError

router = APIRouter(tags=["query"])
log = get_logger(__name__)


def _state(request: Request) -> AppState:
    return request.app.state.legalmed


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/query")
async def submit_query(
    body: QueryRequest,
    request: Request,
    claims: SessionClaims = Depends(get_current_claims),
):
    enforce_scope(claims, claims.tenant_id, body.matter_or_patient_id, Action.QUERY)
    state = _state(request)
    session_id = body.session_id or str(uuid4())

    async def event_stream():
        try:
            search_result = await state.clients.search(
                query=body.question,
                tenant_id=claims.tenant_id,
                matter_or_patient_id=body.matter_or_patient_id,
            )
        except ServiceUnavailableError as exc:
            yield _sse({"type": "error", "error": str(exc)})
            return

        chunks = search_result["chunks"]

        raw_answer_text = ""
        chunk_ids_in_context: list[str] = []
        dropped_chunk_ids: list[str] = []
        prompt_tokens = completion_tokens = 0

        try:
            async for line in state.clients.generate_stream(
                {"question": body.question, "tenant_id": claims.tenant_id, "chunks": chunks}
            ):
                event = json.loads(line)
                if event["type"] == "token":
                    raw_answer_text += event["token"]
                    yield _sse(event)
                elif event["type"] == "final":
                    final = event["final"]
                    raw_answer_text = final["answer_text"]
                    chunk_ids_in_context = final["chunk_ids_in_context"]
                    dropped_chunk_ids = final.get("dropped_chunk_ids", [])
                    prompt_tokens = final.get("prompt_tokens", 0)
                    completion_tokens = final.get("completion_tokens", 0)
        except ServiceUnavailableError as exc:
            yield _sse({"type": "error", "error": str(exc)})
            return

        try:
            validation = await state.clients.validate(
                answer_text=raw_answer_text,
                retrieved_chunks=[c for c in chunks if c["chunk_id"] in chunk_ids_in_context],
                tenant_policy="strip_unverified",
            )
        except ServiceUnavailableError as exc:
            yield _sse({"type": "error", "error": str(exc)})
            return

        citations = [Citation(**c) for c in validation["resolved_citations"]]
        final_payload = {
            "answer_text": validation["verified_answer_text"],
            "citations": [c.model_dump() for c in citations],
            "validation_outcome": validation["validation_outcome"],
        }

        await state.audit_repo.write(
            AuditEvent(
                event_id=str(uuid4()),
                tenant_id=claims.tenant_id,
                user_id=claims.user_id,
                session_id=session_id,
                matter_or_patient_id=body.matter_or_patient_id,
                question=body.question,
                retrieved_chunk_ids=[c["chunk_id"] for c in chunks],
                dropped_chunk_ids=dropped_chunk_ids,
                answer_text=final_payload["answer_text"],
                validation_outcome=ValidationOutcome(validation["validation_outcome"]),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

        yield _sse({"type": "final", "final": final_payload})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
