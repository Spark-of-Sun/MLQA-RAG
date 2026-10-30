"""G6.5 scoped cache on real Valkey, and the provider circuit breaker (G6.8). Model-free."""

from __future__ import annotations

import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from valkey.asyncio import Valkey

from generation.cache import AnswerCache, CacheSettings, cache_key
from generation.llm import CircuitBreaker, LlmUnavailableError, guarded_stream
from lmqa_keys import KeyService, new_key

pytestmark = [pytest.mark.integration, pytest.mark.stage6]


@pytest_asyncio.fixture
async def valkey():
    client = Valkey.from_url(os.environ.get("VALKEY_URL", "redis://127.0.0.1:6379"))
    yield client
    await client.aclose()


def keys_for(org, ws, **over):
    base = {
        "scope_hash": "s1",
        "chunk_set": [("c1", 1), ("c2", 1)],
        "prompt_version": "v1",
        "model": "m",
        "question": "What is the fee?",
    }
    return cache_key(org, ws, **{**base, **over})


@pytest.mark.asyncio
async def test_a_hit_returns_the_answer_and_it_is_stored_encrypted(valkey: Valkey) -> None:
    org, ws, wk = uuid4(), uuid4(), new_key()
    cache = AnswerCache(valkey, KeyService.__new__(KeyService), CacheSettings(enabled=True))
    key = keys_for(org, ws)
    assert await cache.get(key, wk, org, ws) is None
    assert await cache.put(key, "The fee is $5,000 [chunk_1].", wk, org, ws)
    assert await cache.get(key, wk, org, ws) == "The fee is $5,000 [chunk_1]."
    assert (
        await cache.get(keys_for(org, ws, question="  WHAT is   the fee? "), wk, org, ws)
        == "The fee is $5,000 [chunk_1]."
    )
    raw = bytes(await valkey.get(key))
    assert b"5,000" not in raw, "Valkey holds ciphertext only"
    assert b"fee" not in raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"scope_hash": "narrower"},
        {"chunk_set": [("c1", 1)]},
        {"chunk_set": [("c1", 2), ("c2", 1)]},
        {"prompt_version": "v2"},
        {"model": "other"},
        {"question": "A different question?"},
    ],
)
async def test_g6_5_a_changed_scope_chunk_set_prompt_or_model_never_hits(
    valkey: Valkey, change: dict
) -> None:
    org, ws, wk = uuid4(), uuid4(), new_key()
    cache = AnswerCache(valkey, KeyService.__new__(KeyService), CacheSettings(enabled=True))
    await cache.put(keys_for(org, ws), "broad answer", wk, org, ws)
    assert await cache.get(keys_for(org, ws, **change), wk, org, ws) is None


@pytest.mark.asyncio
async def test_g6_5_nothing_is_shared_across_workspaces_even_with_the_same_inputs(
    valkey: Valkey,
) -> None:
    org, ws_a, ws_b = uuid4(), uuid4(), uuid4()
    key_a, key_b = new_key(), new_key()
    cache = AnswerCache(valkey, KeyService.__new__(KeyService), CacheSettings(enabled=True))
    await cache.put(keys_for(org, ws_a), "workspace A answer", key_a, org, ws_a)
    assert keys_for(org, ws_a) != keys_for(org, ws_b)
    assert await cache.get(keys_for(org, ws_b), key_b, org, ws_b) is None
    # Even handed A's cache name and A's workspace key, workspace B's identity cannot open it.
    assert await cache.get(keys_for(org, ws_a), key_a, org, ws_b) is None


@pytest.mark.asyncio
async def test_g6_5_entries_expire_with_the_ttl_and_with_the_daily_key(valkey: Valkey) -> None:
    org, ws, wk = uuid4(), uuid4(), new_key()
    short = AnswerCache(
        valkey, KeyService.__new__(KeyService), CacheSettings(enabled=True, ttl_seconds=1)
    )
    key = keys_for(org, ws, question="expires soon")
    await short.put(key, "short lived", wk, org, ws)
    assert await short.get(key, wk, org, ws) == "short lived"
    await asyncio.sleep(1.5)  # real time: the TTL is configuration
    assert await short.get(key, wk, org, ws) is None
    cache = AnswerCache(valkey, KeyService.__new__(KeyService), CacheSettings(enabled=True))
    key2 = keys_for(org, ws, question="rotates daily")
    await cache.put(key2, "written on day one", wk, org, ws, day=date(2030, 1, 1))
    assert await cache.get(key2, wk, org, ws, day=date(2030, 1, 1)) == "written on day one"
    assert await cache.get(key2, wk, org, ws, day=date(2030, 1, 2)) is None, (
        "yesterday's entry died with yesterday's key"
    )


def test_medical_organizations_are_off_by_default_and_ttl_is_capped() -> None:
    assert CacheSettings.for_deployment("medical").enabled is False
    assert CacheSettings.for_deployment("both").enabled is False
    assert CacheSettings.for_deployment("medical", opted_in=True).enabled is True
    assert CacheSettings.for_deployment("legal").enabled is True
    assert CacheSettings.for_deployment("legal", ttl_seconds=999_999).ttl_seconds == 3600


@pytest.mark.asyncio
async def test_a_disabled_cache_stores_and_returns_nothing(valkey: Valkey) -> None:
    org, ws, wk = uuid4(), uuid4(), new_key()
    cache = AnswerCache(valkey, KeyService.__new__(KeyService), CacheSettings(enabled=False))
    assert await cache.put(keys_for(org, ws, question="phi"), "patient data", wk, org, ws) is False
    assert await valkey.get(keys_for(org, ws, question="phi")) is None
    assert await cache.get(keys_for(org, ws, question="phi"), wk, org, ws) is None


class ControlClient:
    """Control: scripted failures to exercise the breaker. It is not a model."""

    model_id = "control"

    def __init__(self, script: list[str]) -> None:
        self.script, self.calls = script, 0

    async def stream(self, system: str, user: str, *, max_tokens: int):  # noqa: ARG002
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if step == "fail_first":
            msg = "down"
            raise ConnectionError(msg)
        if step == "fail_midway":
            yield "partial "
            msg = "cut"
            raise ConnectionError(msg)
        yield "ok"


async def _collect(client, breaker) -> str:
    return "".join([d async for d in guarded_stream(client, breaker, "s", "u", max_tokens=10)])


@pytest.mark.asyncio
async def test_g6_8_one_retry_only_before_any_token_and_never_after_text_was_produced() -> None:
    retried = ControlClient(["fail_first", "ok"])
    assert await _collect(retried, CircuitBreaker()) == "ok"
    assert retried.calls == 2
    midway = ControlClient(["fail_midway", "ok"])
    with pytest.raises(LlmUnavailableError):
        await _collect(midway, CircuitBreaker())
    assert midway.calls == 1, "a retry after released text could duplicate it, so there is none"


@pytest.mark.asyncio
async def test_g6_8_the_circuit_opens_after_repeated_failures_and_closes_after_the_cooldown() -> (
    None
):
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.4)
    dead = ControlClient(["fail_first"])
    for _ in range(2):
        with pytest.raises(LlmUnavailableError):
            await _collect(dead, breaker)
    assert breaker.is_open
    calls = dead.calls
    with pytest.raises(LlmUnavailableError, match="circuit"):
        await _collect(dead, breaker)
    assert dead.calls == calls, "an open circuit does not call the provider at all"
    await asyncio.sleep(0.6)
    assert not breaker.is_open
    assert await _collect(ControlClient(["ok"]), breaker) == "ok"
