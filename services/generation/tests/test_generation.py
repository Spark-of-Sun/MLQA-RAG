"""Unit tests for generation service."""

from __future__ import annotations

import uuid

import pytest
from generation.client import GenerationClient
from lmqa_models import LLMConfig, RetrievalAlias, RetrievalRecord


@pytest.mark.stage0
@pytest.mark.unit
def test_generation_prompt_synthesis() -> None:
    """Verify prompt synthesis embeds aliases and document provenance."""
    client = GenerationClient()
    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    record = RetrievalRecord(
        request_id=uuid.uuid4(),
        org_id=org_id,
        workspace_id=ws_id,
        user_id="auth0|user1",
        scope_hash="hash",
        query="What is the governing law?",
        aliases=[
            RetrievalAlias(
                alias="chunk_1",
                chunk_id=uuid.uuid4(),
                doc_name="Commercial Lease Agreement",
                page="4",
                section="Governing Law",
                text="This agreement is governed by the laws of New York.",
                content_hash="h1",
            )
        ],
    )

    prompt = client.build_system_prompt(record)
    assert "[chunk_1]" in prompt
    assert "Commercial Lease Agreement" in prompt
    assert "New York" in prompt
    assert "What is the governing law?" in prompt


@pytest.mark.stage0
@pytest.mark.unit
@pytest.mark.asyncio
async def test_generation_offline_grounded_answer() -> None:
    """Verify offline answer synthesis includes valid citation item."""
    cfg = LLMConfig(provider="google", model="gemini-3.8-flash", api_key="")
    client = GenerationClient(config=cfg)

    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    record = RetrievalRecord(
        request_id=uuid.uuid4(),
        org_id=org_id,
        workspace_id=ws_id,
        user_id="auth0|user1",
        scope_hash="hash",
        query="What is the penalty?",
        aliases=[
            RetrievalAlias(
                alias="chunk_1",
                chunk_id=chunk_id,
                doc_name="Loan Agreement",
                page="8",
                section="Default",
                text="Late fee shall be five percent.",
                content_hash="h2",
            )
        ],
    )

    resp = await client.generate(record)
    assert "[chunk_1]" in resp.answer
    assert len(resp.citations) == 1
    assert resp.citations[0].alias == "chunk_1"
    assert resp.citations[0].doc_name == "Loan Agreement"
