"""Generation service entrypoint: ``uvicorn generation.main:app``.

Needs: PG_DSN_GENERATION, VALKEY_URL, a KMS and the trust root, and the provider key for the chosen
LLM (LLM_PROVIDER, LLM_MODEL and ANTHROPIC_API_KEY or OPENAI_API_KEY).
The answer cache is OFF unless
ANSWER_CACHE=on (medical organizations opt in, doc 10.7, D12); its TTL is capped at one hour.
"""

from __future__ import annotations

from pathlib import Path

from generation.app import create_app
from generation.budget import DEFAULT_CONTEXT_BUDGET, DEFAULT_MAX_OUTPUT
from generation.cache import AnswerCache, CacheSettings
from generation.llm import CircuitBreaker, LlmSettings, make_client
from generation.prompt import PromptRegistry
from generation.service import GenerationService
from lmqa_auth.runtime import context_verifier, database, env, key_provider, valkey_client
from lmqa_keys import KeyService
from lmqa_models import HfTokenizer


class _Counter:
    """Token counts with the embedding model's tokenizer; a deliberately conservative estimator."""

    def __init__(self, name: str) -> None:
        self._t = HfTokenizer(name)

    def count(self, text: str) -> int:
        return self._t.count(text)


def build() -> GenerationService:
    """Construct the service from the environment."""
    provider = env("LLM_PROVIDER", "anthropic")
    key = env("ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY")
    keys, valkey = KeyService(key_provider()), valkey_client("GENERATION")
    enabled = env("ANSWER_CACHE", "off") == "on"
    return GenerationService(
        database("GENERATION"),
        keys,
        PromptRegistry(Path(env("PROMPTS_DIR", "prompts"))),
        _Counter(env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")),
        make_client(LlmSettings(provider, env("LLM_MODEL"), key)),
        CircuitBreaker(),
        AnswerCache(valkey, keys, CacheSettings(enabled=enabled)),
        max_output=int(env("LLM_MAX_OUTPUT", str(DEFAULT_MAX_OUTPUT))),
        budget=int(env("LLM_CONTEXT_BUDGET", str(DEFAULT_CONTEXT_BUDGET))),
    )


app = create_app(build(), context_verifier("generation", valkey_client("GENERATION")))
