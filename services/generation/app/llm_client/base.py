from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMCompletion:
    text: str
    completion_tokens: int


class LLMClient(Protocol):
    async def stream_completion(
        self, system_prompt: str, user_prompt: str, max_completion_tokens: int
    ) -> AsyncIterator[str]:
        """Yields completion text incrementally (token-ish chunks)."""
        ...

    def last_completion_tokens(self) -> int:
        """Returns the completion token count for the most recently
        streamed call, once stream_completion has finished iterating."""
        ...
