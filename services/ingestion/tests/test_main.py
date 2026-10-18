from __future__ import annotations

import pytest

from app.main import app as fastapi_app


@pytest.mark.asyncio
async def test_upload_requires_internal_auth(client):
    response = await client.post(
        "/v1/documents",
        data={
            "tenant_id": "t1",
            "matter_or_patient_id": "matter-1",
            "confidentiality_tier": "standard",
            "industry": "legal",
        },
        files={"file": ("contract.pdf", b"4.2 Termination\nEither party may terminate.", "application/pdf")},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_then_get_document(client, internal_headers):
    upload = await client.post(
        "/v1/documents",
        data={
            "tenant_id": "t1",
            "matter_or_patient_id": "matter-1",
            "confidentiality_tier": "standard",
            "industry": "legal",
        },
        files={"file": ("contract.pdf", b"4.2 Termination\nEither party may terminate.", "application/pdf")},
        headers=internal_headers,
    )
    assert upload.status_code == 202
    body = upload.json()
    assert body["status"] == "ingesting"

    fetched = await client.get(f"/v1/documents/{body['document_id']}", headers=internal_headers)
    assert fetched.status_code == 200
    assert fetched.json()["filename"] == "contract.pdf"


@pytest.mark.asyncio
async def test_upload_enqueues_job(client, internal_headers):
    await client.post(
        "/v1/documents",
        data={
            "tenant_id": "t1",
            "matter_or_patient_id": "matter-1",
            "confidentiality_tier": "standard",
            "industry": "legal",
        },
        files={"file": ("contract.pdf", b"text", "application/pdf")},
        headers=internal_headers,
    )
    state = fastapi_app.state.legalmed
    assert len(state.job_queue.enqueued) == 1
    assert state.job_queue.enqueued[0]["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_get_missing_document_is_404(client, internal_headers):
    response = await client.get("/v1/documents/does-not-exist", headers=internal_headers)
    assert response.status_code == 404
