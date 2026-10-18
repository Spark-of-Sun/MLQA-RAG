from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_submit_query_happy_path(client, auth_header):
    response = await client.post(
        "/v1/query",
        json={"question": "What is the contract term?", "matter_or_patient_id": "matter-1"},
        headers=auth_header(),
    )
    assert response.status_code == 200

    events = [
        json.loads(line[len("data: "):])
        for line in response.text.split("\n\n")
        if line.startswith("data: ")
    ]
    final_events = [e for e in events if e["type"] == "final"]
    assert final_events, f"no final event in stream: {events}"
    assert final_events[0]["final"]["validation_outcome"] == "pass"


@pytest.mark.asyncio
async def test_submit_query_wrong_scope_is_forbidden(client, auth_header):
    headers = auth_header(matter_or_patient_id="matter-1")
    response = await client.post(
        "/v1/query",
        json={"question": "x", "matter_or_patient_id": "matter-OUTSIDE-SCOPE"},
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_query_requires_auth(client):
    response = await client.post("/v1/query", json={"question": "x", "matter_or_patient_id": "matter-1"})
    assert response.status_code == 401
