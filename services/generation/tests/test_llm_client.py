from __future__ import annotations

import pytest

from app.llm_client import FakeLLMClient


@pytest.mark.asyncio
async def test_fake_llm_client_cites_the_first_chunk_in_prompt():
    client = FakeLLMClient()
    user_prompt = (
        'Question: x\n\nDocument excerpts:\n'
        '<chunk id="chunk_7" doc="d" page="1">some text</chunk>'
    )
    text = ""
    async for token in client.stream_completion("system", user_prompt, 100):
        text += token
    assert "[chunk_7]" in text
    assert client.last_completion_tokens() > 0


@pytest.mark.asyncio
async def test_fake_llm_client_refuses_without_chunks():
    client = FakeLLMClient()
    text = ""
    async for token in client.stream_completion("system", "Question: x\n\nDocument excerpts:\n", 100):
        text += token
    assert "the provided documents do not address this" in text
