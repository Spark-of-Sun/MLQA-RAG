from __future__ import annotations

import pytest

from app.llm_client.semantic_cache import InMemorySemanticCache, make_cache_key


def test_cache_key_is_stable_for_same_inputs():
    k1 = make_cache_key("t1", "What is the term?", ["c1", "c2"])
    k2 = make_cache_key("t1", "what is the term?  ", ["c2", "c1"])  # case/whitespace/order-insensitive
    assert k1 == k2


def test_cache_key_differs_for_different_chunk_sets():
    k1 = make_cache_key("t1", "q", ["c1"])
    k2 = make_cache_key("t1", "q", ["c2"])
    assert k1 != k2


@pytest.mark.asyncio
async def test_in_memory_cache_roundtrip():
    cache = InMemorySemanticCache()
    key = make_cache_key("t1", "q", ["c1"])
    assert await cache.get(key) is None
    await cache.set(key, "cached answer", ttl_seconds=60)
    assert await cache.get(key) == "cached answer"
