from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_generate_requires_internal_auth(client):
    response = await client.post(
        "/internal/v1/generate",
        json={"question": "x", "tenant_id": "t1", "chunks": []},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_generate_streams_tokens_and_final_event(client, internal_headers):
    response = await client.post(
        "/internal/v1/generate",
        json={
            "question": "What is the contract term?",
            "tenant_id": "t1",
            "chunks": [
                {"chunk_id": "c1", "document_id": "doc1", "text": "The term is 12 months.", "page": 4, "section": "4.2"}
            ],
        },
        headers=internal_headers,
    )
    assert response.status_code == 200

    events = [json.loads(line[len("data: "):]) for line in response.text.split("\n\n") if line.startswith("data: ")]
    final_events = [e for e in events if e["type"] == "final"]
    assert final_events, f"no final event: {events}"

    final = final_events[0]["final"]
    assert "c1" in final["chunk_ids_in_context"]
    assert final["cache_hit"] is False
    assert final["completion_tokens"] > 0


@pytest.mark.asyncio
async def test_generate_second_identical_call_is_a_cache_hit(client, internal_headers):
    payload = {
        "question": "What is the contract term?",
        "tenant_id": "t1",
        "chunks": [
            {"chunk_id": "c1", "document_id": "doc1", "text": "The term is 12 months.", "page": 4, "section": "4.2"}
        ],
    }
    first = await client.post("/internal/v1/generate", json=payload, headers=internal_headers)
    second = await client.post("/internal/v1/generate", json=payload, headers=internal_headers)

    def final_of(response):
        events = [json.loads(line[len("data: "):]) for line in response.text.split("\n\n") if line.startswith("data: ")]
        return [e for e in events if e["type"] == "final"][0]["final"]

    assert final_of(first)["cache_hit"] is False
    assert final_of(second)["cache_hit"] is True
    assert final_of(second)["answer_text"] == final_of(first)["answer_text"]


@pytest.mark.asyncio
async def test_generate_drops_oversized_chunk_entirely(client, internal_headers):
    big_text = "word " * 3000
    response = await client.post(
        "/internal/v1/generate",
        json={
            "question": "x",
            "tenant_id": "t1",
            "chunks": [
                {"chunk_id": "small", "document_id": "d", "text": "short", "page": 1},
                {"chunk_id": "huge", "document_id": "d", "text": big_text, "page": 2},
            ],
            "max_prompt_tokens": 400,
        },
        headers=internal_headers,
    )
    events = [json.loads(line[len("data: "):]) for line in response.text.split("\n\n") if line.startswith("data: ")]
    final = [e for e in events if e["type"] == "final"][0]["final"]
    assert "huge" in final["dropped_chunk_ids"]
    assert "huge" not in final["chunk_ids_in_context"]
