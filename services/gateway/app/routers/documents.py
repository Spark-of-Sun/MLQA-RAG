from __future__ import annotations

from common.auth.jwt import SessionClaims
from common.models import Action
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.auth.dependencies import get_current_claims
from app.middleware.tenant_scope import enforce_scope
from app.schemas.requests import DocumentSummary
from app.state import AppState

router = APIRouter(tags=["documents"])


def _state(request: Request) -> AppState:
    return request.app.state.legalmed


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(
    request: Request,
    matter_or_patient_id: str | None = None,
    claims: SessionClaims = Depends(get_current_claims),
):
    enforce_scope(claims, claims.tenant_id, matter_or_patient_id, Action.READ)
    records = await _state(request).document_repo.list_for_scope(claims.tenant_id, matter_or_patient_id)
    return [DocumentSummary(**r) for r in records]


@router.get("/documents/{document_id}", response_model=DocumentSummary)
async def get_document(
    document_id: str,
    request: Request,
    claims: SessionClaims = Depends(get_current_claims),
):
    record = await _state(request).document_repo.get(document_id)
    if record is None or record["tenant_id"] != claims.tenant_id:
        raise HTTPException(status_code=404, detail="document not found")
    enforce_scope(claims, claims.tenant_id, record["matter_or_patient_id"], Action.READ)
    return DocumentSummary(**record)


@router.post("/documents", response_model=DocumentSummary, status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    matter_or_patient_id: str = Form(...),
    confidentiality_tier: str = Form(...),
    claims: SessionClaims = Depends(get_current_claims),
):
    """Proxies the upload to the Ingestion service (services/ingestion,
    not built yet) and records it as 'ingesting'. Until Ingestion exists,
    this writes the record locally so the Gateway's contract and auth/
    scope enforcement can be tested end-to-end on their own.
    """
    enforce_scope(claims, claims.tenant_id, matter_or_patient_id, Action.QUERY)

    # TODO(services/ingestion): forward `file` to
    # POST {ingestion_base_url}/v1/documents and use its document_id,
    # instead of minting one locally, once that service exists.
    record = await _state(request).document_repo.put_ingesting(
        tenant_id=claims.tenant_id,
        filename=file.filename or "unnamed",
        matter_or_patient_id=matter_or_patient_id,
        confidentiality_tier=confidentiality_tier,
    )
    return DocumentSummary(**record)
