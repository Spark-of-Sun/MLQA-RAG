from __future__ import annotations

import hashlib
import json
import os
from typing import Protocol


class SemanticCache(Protocol):
    async def get(self, cache_key: str) -> str | None: ...
    async def set(self, cache_key: str, answer_text: str, ttl_seconds: int) -> None: ...


def make_cache_key(tenant_id: str, question: str, chunk_ids_in_context: list[str]) -> str:
    """NOTE: this is exact-match caching (same tenant + same question text
    + same chunk set), not true semantic/embedding similarity — a stand-in
    for GPTCache's near-duplicate detection per docs/architecture.md §4
    step 4. Real semantic caching (embedding-based similarity) is a TODO;
    this still gives repeat/near-identical queries a cache hit, just not
    paraphrased ones.
    """
    payload = json.dumps(
        {"tenant_id": tenant_id, "question": question.strip().lower(), "chunk_ids": sorted(chunk_ids_in_context)},
        sort_keys=True,
    )
    return "gencache:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemorySemanticCache:
    """Local/test stand-in — no real Redis connection needed."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, cache_key: str) -> str | None:
        return self._store.get(cache_key)

    async def set(self, cache_key: str, answer_text: str, ttl_seconds: int) -> None:
        self._store[cache_key] = answer_text


class RedisSemanticCache:
    """Real backend — Redis-backed, TTL'd, per docs/architecture.md §4
    step 4 and the Cache row in §6's data layer table.
    """

    def __init__(self, redis_url: str | None = None):
        import redis.asyncio as redis_asyncio

        self._redis = redis_asyncio.from_url(
            redis_url or os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
        )

    async def get(self, cache_key: str) -> str | None:
        return await self._redis.get(cache_key)

    async def set(self, cache_key: str, answer_text: str, ttl_seconds: int) -> None:
        await self._redis.set(cache_key, answer_text, ex=ttl_seconds)


def build_semantic_cache() -> SemanticCache:
    backend = os.environ.get("SEMANTIC_CACHE_BACKEND", "redis")
    if backend == "redis":
        return RedisSemanticCache()
    if backend == "in-memory":
        return InMemorySemanticCache()
    raise ValueError(f"unknown SEMANTIC_CACHE_BACKEND: {backend}")
