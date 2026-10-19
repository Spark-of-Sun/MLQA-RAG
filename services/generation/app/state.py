from __future__ import annotations

import os

from prompt_registry_client import PromptRegistryClient

from app.compression import Compressor, get_compressor
from app.llm_client import LLMClient, get_llm_client
from app.llm_client.semantic_cache import SemanticCache, build_semantic_cache
from app.token_budget import TokenCounter, get_token_counter


class AppState:
    def __init__(
        self,
        token_counter: TokenCounter,
        compressor: Compressor,
        llm_client: LLMClient,
        semantic_cache: SemanticCache,
        registry_client: PromptRegistryClient,
    ):
        self.token_counter = token_counter
        self.compressor = compressor
        self.llm_client = llm_client
        self.semantic_cache = semantic_cache
        self.registry_client = registry_client

    @classmethod
    async def create(cls) -> AppState:
        return cls(
            token_counter=get_token_counter(),
            compressor=get_compressor(),
            llm_client=get_llm_client(),
            semantic_cache=build_semantic_cache(),
            registry_client=PromptRegistryClient(
                backend=os.environ.get("PROMPT_REGISTRY_BACKEND", "local-file"),
                templates_dir=os.environ.get("PROMPT_TEMPLATES_DIR", "prompts/templates"),
            ),
        )

    async def aclose(self) -> None:
        pass
