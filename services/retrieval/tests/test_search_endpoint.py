from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_search_requires_internal_auth(client):
    response = await client.post(
        "/internal/v1/search",
        json={"query": "termination", "tenant_id": "t1", "matter_or_patient_id": "matter-1"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_returns_ranked_chunks_for_tenant(client, internal_headers):
    response = await client.post(
        "/internal/v1/search",
        json={"query": "terminate days notice", "tenant_id": "t1", "matter_or_patient_id": "matter-1"},
        headers=internal_headers,
    )
    assert response.status_code == 200
    body = response.json()
    chunk_ids = [c["chunk_id"] for c in body["chunks"]]
    assert "c2" in chunk_ids  # most relevant to "terminate days notice"
    assert "c4" not in chunk_ids  # different tenant — must never appear
    assert "c5" not in chunk_ids  # privileged tier not in default allowed list


@pytest.mark.asyncio
async def test_search_reports_dropped_chunk_count(client, internal_headers):
    response = await client.post(
        "/internal/v1/search",
        json={"query": "anything", "tenant_id": "t1", "matter_or_patient_id": "matter-1"},
        headers=internal_headers,
    )
    body = response.json()
    # c4 (wrong tenant) and c5 (wrong tier) should both be dropped
    assert body["dropped_chunk_count"] == 2


@pytest.mark.asyncio
async def test_search_honors_confidentiality_tier_allowlist(client, internal_headers):
    response = await client.post(
        "/internal/v1/search",
        json={
            "query": "privileged",
            "tenant_id": "t1",
            "matter_or_patient_id": "matter-1",
            "confidentiality_tiers_allowed": ["standard", "privileged"],
        },
        headers=internal_headers,
    )
    body = response.json()
    chunk_ids = [c["chunk_id"] for c in body["chunks"]]
    assert "c5" in chunk_ids
