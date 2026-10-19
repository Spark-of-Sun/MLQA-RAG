from __future__ import annotations

import pytest
from common.models import Action


@pytest.mark.asyncio
async def test_upload_then_list_document(client, auth_header):
    # Uploading needs Action.QUERY; listing needs Action.READ — an
    # ADMIN-scoped role covers both, per RoleScope.covers(). A real user
    # exercising this flow would hold separate query+read grants; this
    # test just needs one role that satisfies both checks.
    headers = auth_header(action=Action.ADMIN)
    upload = await client.post(
        "/v1/documents",
        data={"matter_or_patient_id": "matter-1", "confidentiality_tier": "standard"},
        files={"file": ("contract.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 202
    document_id = upload.json()["document_id"]

    listing = await client.get("/v1/documents", params={"matter_or_patient_id": "matter-1"}, headers=headers)
    assert listing.status_code == 200
    assert any(d["document_id"] == document_id for d in listing.json())


@pytest.mark.asyncio
async def test_get_missing_document_is_404(client, auth_header):
    response = await client.get("/v1/documents/does-not-exist", headers=auth_header())
    assert response.status_code == 404
