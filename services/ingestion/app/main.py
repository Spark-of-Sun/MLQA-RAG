from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from common.auth.service_token import ServiceAuthError, verify_internal_service_key
from common.logging import configure_logging, get_logger
from common.models import ConfidentialityTier, TenantIndustry

from app.schemas.requests import DocumentSummary
from app.state import AppState

configure_logging(service_name="ingestion")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.legalmed = await AppState.create()
    log.info("ingestion_startup")
    yield
    await app.state.legalmed.aclose()
    log.info("ingestion_shutdown")


app = FastAPI(title="Legal/Medical QA — Ingestion", version="0.1.0", lifespan=lifespan)


def _state(request: Request) -> AppState:
    return request.app.state.legalmed


def _require_internal_auth(request: Request) -> None:
    try:
        verify_internal_service_key(request.headers.get("X-Internal-Service-Key"))
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/v1/documents", response_model=DocumentSummary, status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
    matter_or_patient_id: str = Form(...),
    confidentiality_tier: ConfidentialityTier = Form(...),
    industry: TenantIndustry = Form(...),
):
    """Called by the Gateway (services/gateway/app/routers/documents.py),
    never directly by the browser. Stores the original file in object
    storage, records 'ingesting' status, and enqueues the background job —
    returns immediately (ingestion of a 200-page contract can take minutes).
    """
    _require_internal_auth(request)
    state = _state(request)

    file_bytes = await file.read()
    object_store_key = f"{tenant_id}/{uuid4()}/{file.filename}"
    state.object_store.put_object(object_store_key, file_bytes)

    record = await state.document_repo.create_ingesting(
        tenant_id=tenant_id,
        filename=file.filename or "unnamed",
        matter_or_patient_id=matter_or_patient_id,
        confidentiality_tier=confidentiality_tier,
        industry=industry,
        object_store_key=object_store_key,
    )

    await state.job_queue.enqueue_ingestion_job(
        document_id=record["document_id"],
        tenant_id=tenant_id,
        matter_or_patient_id=matter_or_patient_id,
        confidentiality_tier=confidentiality_tier.value,
        industry=industry.value,
        object_store_key=object_store_key,
        filename=record["filename"],
    )

    return DocumentSummary(**record)


@app.get("/v1/documents", response_model=list[DocumentSummary])
async def list_documents(request: Request, tenant_id: str, matter_or_patient_id: str | None = None):
    _require_internal_auth(request)
    records = await _state(request).document_repo.list_for_scope(tenant_id, matter_or_patient_id)
    return [DocumentSummary(**r) for r in records]


@app.get("/v1/documents/{document_id}", response_model=DocumentSummary)
async def get_document(document_id: str, request: Request):
    _require_internal_auth(request)
    record = await _state(request).document_repo.get(document_id)
    if record is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentSummary(**record)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error"})

