from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_validate_requires_internal_auth(client):
    response = await client.post(
        "/internal/v1/validate",
        json={"answer_text": "x [c1].", "retrieved_chunks": [], "tenant_policy": "strip_unverified"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validate_endpoint_returns_pass_for_supported_citation(client, internal_headers):
    response = await client.post(
        "/internal/v1/validate",
        json={
            "answer_text": "The term is 12 months [c1].",
            "retrieved_chunks": [
                {"chunk_id": "c1", "document_id": "doc1", "text": "The term of this agreement is 12 months.", "page": 4, "section": "4.2"}
            ],
            "tenant_policy": "strip_unverified",
            "entailment_support_threshold": 0.3,
        },
        headers=internal_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["validation_outcome"] == "pass"
    assert body["resolved_citations"][0]["chunk_id"] == "c1"


@pytest.mark.asyncio
async def test_validate_endpoint_strips_unverified_citation(client, internal_headers):
    response = await client.post(
        "/internal/v1/validate",
        json={
            "answer_text": "The term is 99 years [c1].",
            "retrieved_chunks": [
                {"chunk_id": "c1", "document_id": "doc1", "text": "Completely unrelated clause about confidentiality.", "page": 1, "section": "1.1"}
            ],
            "tenant_policy": "strip_unverified",
            "entailment_support_threshold": 0.5,
        },
        headers=internal_headers,
    )
    body = response.json()
    assert body["validation_outcome"] == "stripped_unverified"
    assert "[unverified]" in body["verified_answer_text"]
