"""The provider-agnostic LLM client (doc 11.8, 10.9). NOT executed in the build sandbox (no keys).

The model gets no tools and no network access: both adapters call plain text completion with
streaming. The provider is chosen per organization (no-retention terms by contract; a BAA for
medical). A circuit breaker protects the provider budget and the latency of everyone else, and a
single retry is made only if the failure happens before the first token (so a retry can never
duplicate released text).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_TIMEOUT: Final = 60.0


class LlmUnavailableError(RuntimeError):
    """The provider failed or its circuit is open. The query fails with a clear error."""


class LlmClient(Protocol):
    """A streaming text model."""

    model_id: str

    def stream(self, system: str, user: str, *, max_tokens: int) -> AsyncIterator[str]:
        """Yield text deltas. No tools, no function calling."""
        ...


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """Per-organization provider settings. The key comes from the secret manager, never code."""

    provider: str  # 'anthropic' or 'openai'
    model: str
    api_key: str
    timeout: float = DEFAULT_TIMEOUT


class AnthropicClient:
    """Anthropic Messages API with streaming."""

    def __init__(self, settings: LlmSettings) -> None:
        """Create the async client."""
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        self._client = AsyncAnthropic(
            api_key=settings.api_key, timeout=settings.timeout, max_retries=0
        )
        self.model_id = f"anthropic:{settings.model}"
        self._model = settings.model

    async def stream(self, system: str, user: str, *, max_tokens: int) -> AsyncIterator[str]:
        """Yield text deltas from a streamed message."""
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as response:
            async for delta in response.text_stream:
                yield delta


class OpenAiClient:
    """OpenAI Chat Completions with streaming."""

    def __init__(self, settings: LlmSettings) -> None:
        """Create the async client."""
        from openai import AsyncOpenAI  # noqa: PLC0415

        self._client = AsyncOpenAI(
            api_key=settings.api_key, timeout=settings.timeout, max_retries=0
        )
        self.model_id = f"openai:{settings.model}"
        self._model = settings.model

    async def stream(self, system: str, user: str, *, max_tokens: int) -> AsyncIterator[str]:
        """Yield text deltas from a streamed completion."""
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            stream=True,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        async for part in response:
            if part.choices and part.choices[0].delta.content:
                yield part.choices[0].delta.content


def make_client(settings: LlmSettings) -> LlmClient:
    """Build the client for the organization's provider."""
    if settings.provider == "anthropic":
        return AnthropicClient(settings)
    if settings.provider == "openai":
        return OpenAiClient(settings)
    msg = f"unknown LLM provider {settings.provider!r}"
    raise ValueError(msg)


class CircuitBreaker:
    """Opens after consecutive failures and closes again after a cool-down (configuration)."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0) -> None:
        """Both values are configuration; tests use small ones."""
        self._threshold, self._cooldown = failure_threshold, cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        """True while calls are being refused."""
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self._cooldown:
            self._opened_at, self._failures = None, 0  # half-open: let the next call try
            return False
        return True

    def record_success(self) -> None:
        """A call worked: reset the failure count."""
        self._failures, self._opened_at = 0, None

    def record_failure(self) -> None:
        """A call failed: open the circuit at the threshold."""
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()


async def guarded_stream(
    client: LlmClient, breaker: CircuitBreaker, system: str, user: str, *, max_tokens: int
) -> AsyncIterator[str]:
    """Stream through the breaker; retry once only if nothing was produced yet."""
    if breaker.is_open:
        msg = "the model provider circuit is open"
        raise LlmUnavailableError(msg)
    for attempt in (1, 2):
        produced = False
        try:
            async for delta in client.stream(system, user, max_tokens=max_tokens):
                produced = True
                yield delta
        except Exception as exc:
            breaker.record_failure()
            if produced or attempt == 2:  # noqa: PLR2004 - a single retry
                msg = "the model provider failed"
                raise LlmUnavailableError(msg) from exc
            continue
        breaker.record_success()
        return
