"""The ingestion HTTP API (doc 11.1, 15.7): the document lifecycle behind the Gateway.

The Gateway only routes; ingestion owns uploads, so it (not the Gateway) holds the object-store
credentials and mints presigned URLs. A document outside the caller's scope is 404, never 403.
Completion runs in the background and the client polls the document's status. (Production moves
that work onto the Procrastinate worker pool; the MVP runs it as an in-process background task.)
"""

from __future__ import annotations

import base64
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ingestion.pipeline import DocumentHeldError, DocumentNotFoundError, IngestionPipeline
from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims, problem
from lmqa_db import DbContext

LOG = logging.getLogger("ingestion")
Claims = Annotated[ContextClaims, Depends(context_claims())]
WriteClaims = Annotated[ContextClaims, Depends(context_claims(state_changing=True))]


class UploadIn(BaseModel):
    """Start an upload: metadata and the SHA-256 the client must send."""

    title: str = Field(min_length=1, max_length=300)
    visibility: str = Field(pattern="^(private|matter)$")
    matter_id: UUID | None = None
    tier: int = Field(default=1, ge=1, le=4)
    declared_type: str = Field(pattern="^(pdf|docx|html|htm|xml|jats|spl|ecfr|txt)$")
    sha256_hex: str = Field(pattern="^[0-9a-fA-F]{64}$")


class AccessIn(BaseModel):
    """Change who can read a document."""

    visibility: str = Field(pattern="^(private|matter)$")
    matter_id: UUID | None = None
    tier: int = Field(ge=1, le=4)


def _info(i: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "id": str(i.doc_id),
        "title": i.title,
        "status": i.status,
        "visibility": i.visibility,
        "tier": i.tier,
        "matter_id": str(i.matter_id) if i.matter_id else None,
        "owner_id": str(i.owner_id),
        "failure_reason": i.failure_reason,
        "created_at": i.created_at,
    }


def create_app(pipeline: IngestionPipeline, verifier: ContextVerifier) -> FastAPI:  # noqa: C901 - one route table
    """Build the app around a constructed pipeline and this service's own token verifier."""
    app = FastAPI(title="ingestion", docs_url=None, redoc_url=None)
    app.state.verifier = verifier
    not_found = problem(404, "Not Found")

    async def run(ctx: DbContext, doc_id: UUID, declared: str, sha: str) -> None:
        try:
            await pipeline.complete_upload(ctx, doc_id, declared, sha)
        except Exception:
            LOG.exception("ingestion of %s failed", doc_id)

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/v1/documents/uploads", status_code=201)
    async def start_upload(body: UploadIn, claims: WriteClaims) -> dict[str, Any]:
        ctx = claims.db_context()
        ticket = await pipeline.create_upload(
            ctx, body.title, body.visibility, body.matter_id, body.tier
        )
        digest = base64.b64encode(bytes.fromhex(body.sha256_hex)).decode()
        url = pipeline.c.objects.presign_quarantine_upload(
            ctx.org, ctx.ws, ticket.doc_id, digest, ttl=60
        )
        return {
            "id": str(ticket.doc_id),
            "upload_url": url,
            "required_headers": {"x-amz-checksum-sha256": digest},
            "expires_in": 60,
        }

    @app.post("/internal/v1/documents/{doc_id}/complete", status_code=202, response_model=None)
    async def complete(
        doc_id: UUID, body: UploadIn, claims: WriteClaims, tasks: BackgroundTasks
    ) -> dict[str, str] | JSONResponse:
        ctx = claims.db_context()
        try:
            await pipeline.get_document(ctx, doc_id)
        except DocumentNotFoundError:
            return not_found
        tasks.add_task(run, ctx, doc_id, body.declared_type, body.sha256_hex)
        return {"id": str(doc_id), "status": "scanning"}

    @app.get("/internal/v1/documents")
    async def list_documents(claims: Claims) -> dict[str, Any]:
        return {"documents": [_info(i) for i in await pipeline.list_documents(claims.db_context())]}

    @app.get("/internal/v1/documents/{doc_id}", response_model=None)
    async def get_document(doc_id: UUID, claims: Claims) -> dict[str, Any] | JSONResponse:
        try:
            return _info(await pipeline.get_document(claims.db_context(), doc_id))
        except DocumentNotFoundError:
            return not_found

    @app.patch("/internal/v1/documents/{doc_id}", response_model=None)
    async def change_access(
        doc_id: UUID, body: AccessIn, claims: WriteClaims, tasks: BackgroundTasks
    ) -> dict[str, str] | JSONResponse:
        ctx = claims.db_context()
        try:
            await pipeline.change_access(
                ctx, doc_id, visibility=body.visibility, matter_id=body.matter_id, tier=body.tier
            )
        except DocumentNotFoundError:
            return not_found
        tasks.add_task(pipeline.apply_outbox, ctx, doc_id)
        return {"id": str(doc_id), "index_state": "stale"}

    @app.delete("/internal/v1/documents/{doc_id}", status_code=204, response_model=None)
    async def delete(doc_id: UUID, claims: WriteClaims) -> Response:
        try:
            await pipeline.delete_document(claims.db_context(), doc_id)
        except DocumentNotFoundError:
            return not_found
        except DocumentHeldError:
            return problem(409, "Document is under legal hold or retention")
        return Response(status_code=204)

    @app.get("/internal/v1/documents/{doc_id}/download", response_model=None)
    async def download(doc_id: UUID, claims: Claims) -> Response:
        try:
            data = await pipeline.download(claims.db_context(), doc_id)
        except DocumentNotFoundError:
            return not_found
        return Response(
            data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"}
        )

    return app
