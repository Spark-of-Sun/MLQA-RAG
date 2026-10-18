from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.auth.service_token import ServiceAuthError, verify_internal_service_key
from common.logging import configure_logging, get_logger

from app.hybrid_search import hybrid_search
from app.reranker import get_reranker
from app.schemas.requests import RankedChunkResponse, SearchRequest, SearchResponse

configure_logging(service_name="retrieval")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.state import AppState

    app.state.legalmed = await AppState.create()
    log.info("retrieval_startup")
    yield
    await app.state.legalmed.aclose()
    log.info("retrieval_shutdown")


app = FastAPI(title="Legal/Medical QA — Retrieval", version="0.1.0", lifespan=lifespan)


def _require_internal_auth(request: Request) -> None:
    try:
        verify_internal_service_key(request.headers.get("X-Internal-Service-Key"))
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/internal/v1/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request):
    """Called only by the Gateway. Owns hybrid search, metadata filtering
    and re-ranking — never prompt assembly or LLM calls (docs/api-contracts/
    retrieval.yaml is the contract this must match).
    """
    _require_internal_auth(request)
    state = request.app.state.legalmed
    reranker = get_reranker()

    ranked, dropped_count = hybrid_search(
        query=body.query,
        tenant_id=body.tenant_id,
        matter_or_patient_id=body.matter_or_patient_id,
        confidentiality_tiers_allowed=body.confidentiality_tiers_allowed,
        vector_search=state.vector_search,
        reranker=reranker,
        top_k_dense=body.top_k_dense,
        top_k_sparse=body.top_k_sparse,
        rerank_top_k=body.rerank_top_k,
    )

    return SearchResponse(
        query=body.query,
        chunks=[
            RankedChunkResponse(
                chunk_id=rc.chunk.chunk_id,
                document_id=rc.chunk.document_id,
                text=rc.chunk.text,
                page=rc.chunk.page,
                section=rc.chunk.section,
                confidentiality_tier=rc.chunk.confidentiality_tier,
                matter_or_patient_id=rc.chunk.matter_or_patient_id,
                effective_date=rc.chunk.effective_date,
                dense_score=rc.dense_score,
                sparse_score=rc.sparse_score,
                rerank_score=rc.rerank_score,
            )
            for rc in ranked
        ],
        dropped_chunk_count=dropped_count,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
