"""Ingestion FastAPI endpoints for document upload, processing, and erasure."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, status
from lmqa_db import DatabaseConfig, TenantContext, build_set_local_statements
from pydantic import BaseModel, Field

from ingestion.models import DocumentTarget, IngestionRequest
from ingestion.pipeline import IngestionPipeline


class UploadInitRequest(BaseModel):
    """Payload to request an upload session."""

    title: str = Field(description="Document title or filename")
    content_type: str = Field(
        default="application/pdf", description="MIME content type of document"
    )
    size_bytes: int = Field(default=0, description="Declared document byte size")


class UploadInitResponse(BaseModel):
    """Response returned upon upload session initialization."""

    document_id: UUID
    status: str
    quarantine_key: str


class UploadDirectQuery(BaseModel):
    """Query parameters for direct upload."""

    title: str = Field(default="uploaded_document", description="Document title")
    expected_sha256: str | None = Field(default=None, description="Expected SHA-256 checksum")


router = APIRouter(prefix="/v1/documents", tags=["documents"])
pipeline = IngestionPipeline()
db_config = DatabaseConfig.from_env()


@router.post("/uploads", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
async def init_upload(
    req: UploadInitRequest,
    x_org_id: Annotated[UUID, Header(alias="X-Org-Id")],
    x_workspace_id: Annotated[UUID, Header(alias="X-Workspace-Id")],
) -> UploadInitResponse:
    """Initialize an upload session and record document in uploading state."""
    doc_id = await pipeline.init_upload(
        org_id=x_org_id,
        workspace_id=x_workspace_id,
        title=req.title,
        content_type=req.content_type,
        size_bytes=req.size_bytes,
    )
    quarantine_key = f"{x_org_id}/quarantine/{doc_id}"
    return UploadInitResponse(
        document_id=doc_id,
        status="uploading",
        quarantine_key=quarantine_key,
    )


@router.post("/{document_id}/upload-direct", status_code=status.HTTP_200_OK)
async def upload_direct(
    document_id: UUID,
    request: Request,
    x_org_id: Annotated[UUID, Header(alias="X-Org-Id")],
    x_workspace_id: Annotated[UUID, Header(alias="X-Workspace-Id")],
    query: Annotated[UploadDirectQuery | None, Query()] = None,
) -> dict[str, Any]:
    """Directly upload file content and execute ingestion pipeline."""
    q = query or UploadDirectQuery()
    raw_bytes = await request.body()
    content_type = request.headers.get("content-type", "application/pdf")

    target = DocumentTarget(
        doc_id=document_id,
        org_id=x_org_id,
        workspace_id=x_workspace_id,
        title=q.title,
    )
    req = IngestionRequest(
        target=target,
        raw_data=raw_bytes,
        declared_content_type=content_type,
        expected_sha256=q.expected_sha256,
    )

    try:
        chunks = await pipeline.process_document(req)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "document_id": document_id,
        "status": "available",
        "chunks_indexed": len(chunks),
        "content_type": content_type,
    }


@router.get("/{document_id}", status_code=status.HTTP_200_OK)
async def get_document(
    document_id: UUID,
    x_org_id: Annotated[UUID, Header(alias="X-Org-Id")],
    x_workspace_id: Annotated[UUID, Header(alias="X-Workspace-Id")],
) -> dict[str, Any]:
    """Retrieve document status and chunk count under tenant context."""
    dsn = db_config.get_asyncpg_dsn("ingestion")
    conn = await asyncpg.connect(dsn, timeout=5)
    try:
        ctx = TenantContext(org_id=x_org_id, workspace_id=x_workspace_id)
        tr = conn.transaction()
        await tr.start()
        for stmt in build_set_local_statements(ctx):
            await conn.execute(stmt)

        row = await conn.fetchrow(
            """
            SELECT id, org_id, workspace_id, title, status, created_at
            FROM documents WHERE id = $1
            """,
            document_id,
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or access denied",
            )

        chunk_count = await conn.fetchval(
            "SELECT count(*) FROM document_chunks WHERE doc_id = $1",
            document_id,
        )
        await tr.rollback()
        return {
            "id": row["id"],
            "org_id": row["org_id"],
            "workspace_id": row["workspace_id"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "chunk_count": chunk_count,
        }
    finally:
        await conn.close()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    x_org_id: Annotated[UUID, Header(alias="X-Org-Id")],
    x_workspace_id: Annotated[UUID, Header(alias="X-Workspace-Id")],
) -> None:
    """Cryptographically delete document, chunks, vectors, and storage object."""
    await pipeline.delete_document(
        org_id=x_org_id,
        workspace_id=x_workspace_id,
        doc_id=document_id,
    )


app = FastAPI(title="LMQA Ingestion Service", version="0.1.0")
app.include_router(router)


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    """Service liveness probe."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    """Service readiness probe."""
    return {"status": "ready"}
