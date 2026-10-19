from __future__ import annotations

import json
from contextlib import asynccontextmanager

from common.auth.service_token import ServiceAuthError, verify_internal_service_key
from common.logging import configure_logging, get_logger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.llm_client.semantic_cache import make_cache_key
from app.prompt_assembly import assemble_prompt
from app.prompt_assembly.templates import get_active_template
from app.schemas.requests import GenerateRequest
from app.state import AppState
from app.token_budget import trim_chunks_by_budget

configure_logging(service_name="generation")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.legalmed = await AppState.create()
    log.info("generation_startup")
    yield
    await app.state.legalmed.aclose()
    log.info("generation_shutdown")


app = FastAPI(title="Legal/Medical QA — Generation", version="0.1.0", lifespan=lifespan)


def _require_internal_auth(request: Request) -> None:
    try:
        verify_internal_service_key(request.headers.get("X-Internal-Service-Key"))
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/internal/v1/generate")
async def generate(body: GenerateRequest, request: Request):
    """Called only by the Gateway. Owns token-budget enforcement,
    compression, prompt assembly, and the LLM call — never citation
    correctness (that's Citation Validator's job, downstream of this).
    Matches docs/api-contracts/generation.yaml.
    """
    _require_internal_auth(request)
    state: AppState = request.app.state.legalmed

    async def event_stream():
        trim_result = trim_chunks_by_budget(body.chunks, body.max_prompt_tokens, state.token_counter)
        if trim_result.dropped_chunk_ids:
            log.info(
                "chunks_dropped_at_budget_trim",
                tenant_id=body.tenant_id,
                dropped_chunk_ids=trim_result.dropped_chunk_ids,
            )

        compressed_chunks = [
            chunk.model_copy(update={"text": state.compressor.compress(chunk.text)})
            for chunk in trim_result.kept
        ]

        template = get_active_template(body.tenant_id, state.registry_client)
        assembled = assemble_prompt(body.question, compressed_chunks, template)

        cache_key = make_cache_key(body.tenant_id, body.question, assembled.chunk_ids_in_context)
        cached_answer = await state.semantic_cache.get(cache_key)

        if cached_answer is not None:
            final_payload = {
                "answer_text": cached_answer,
                "chunk_ids_in_context": assembled.chunk_ids_in_context,
                "dropped_chunk_ids": trim_result.dropped_chunk_ids,
                "prompt_tokens": trim_result.prompt_tokens_estimate,
                "completion_tokens": 0,
                "cache_hit": True,
            }
            yield _sse({"type": "final", "final": final_payload})
            return

        answer_text = ""
        async for token in state.llm_client.stream_completion(
            assembled.system_prompt, assembled.user_prompt, body.max_completion_tokens
        ):
            answer_text += token
            yield _sse({"type": "token", "token": token})

        await state.semantic_cache.set(cache_key, answer_text, ttl_seconds=3600)

        final_payload = {
            "answer_text": answer_text,
            "chunk_ids_in_context": assembled.chunk_ids_in_context,
            "dropped_chunk_ids": trim_result.dropped_chunk_ids,
            "prompt_tokens": trim_result.prompt_tokens_estimate,
            "completion_tokens": state.llm_client.last_completion_tokens(),
            "cache_hit": False,
        }
        yield _sse({"type": "final", "final": final_payload})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
