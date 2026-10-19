import os

from .base import LLMClient, LLMCompletion
from .fake_backend import FakeLLMClient


def get_llm_client(provider: str | None = None) -> LLMClient:
    provider = provider or os.environ.get("LLM_PROVIDER", "fake")
    if provider == "anthropic":
        from .anthropic_backend import AnthropicLLMClient

        return AnthropicLLMClient()
    if provider in ("gemini", "google"):
        from .gemini_backend import GeminiLLMClient

        return GeminiLLMClient()
    if provider == "fake":
        return FakeLLMClient()
    raise ValueError(f"unknown LLM_PROVIDER: {provider}")


__all__ = ["FakeLLMClient", "LLMClient", "LLMCompletion", "get_llm_client"]
