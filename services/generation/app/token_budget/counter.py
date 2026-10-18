from __future__ import annotations

import os
from typing import Protocol


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ApproxTokenCounter:
    """Dependency-free, deterministic token count approximation
    (~4 characters per token, a common rule of thumb for English text).
    This is the DEFAULT counter — tiktoken's real encodings are fetched
    from a remote CDN on first use unless pre-cached, which makes it a
    poor default for offline/sandboxed test runs. Good enough for
    trim-by-relevance decisions; not used for real LLM billing accuracy.
    """

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)


class TiktokenCounter:
    """Real counter — exact token count for the configured model's
    tokenizer, per docs/architecture.md §4 step 1 ('Count before sending').
    Requires network access on first call unless tiktoken's BPE file is
    already cached locally; use ApproxTokenCounter in offline/local dev.
    """

    def __init__(self, model: str | None = None):
        import tiktoken

        try:
            self._encoding = tiktoken.encoding_for_model(model or os.environ.get("LLM_MODEL", "gpt-4"))
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))


def get_token_counter(backend: str | None = None) -> TokenCounter:
    backend = backend or os.environ.get("TOKEN_COUNTER_BACKEND", "approx")
    if backend == "tiktoken":
        return TiktokenCounter()
    if backend == "approx":
        return ApproxTokenCounter()
    raise ValueError(f"unknown TOKEN_COUNTER_BACKEND: {backend}")

