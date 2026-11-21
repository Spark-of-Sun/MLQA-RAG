"""Draft answers and entailment checks (blueprint 11.4 to 11.6).

`draft()` enforces the hard token budget before any provider call (11.4): sources are admitted whole, in
rank order, until the budget is reached; nothing is truncated mid-chunk. The model sees request-local
aliases only. `entailment()` is the MVP stand-in for the pinned NLI model (V6, see docs/mvp.md): a strict
second pass whose verdicts can only remove sentences, never approve one the deterministic validator rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from generation.llm_client import GeminiClient
from generation.prompts import (
    ANSWER_SCHEMA,
    VERIFY_SCHEMA,
    answer_user_prompt,
    estimate_tokens,
    load_prompts,
    verify_user_prompt,
)
from lmqa_models.rag import Source
from lmqa_models.settings import Settings


@dataclass(frozen=True)
class Draft:
    data: dict[str, Any]
    sources: list[Source]  # the sources actually sent, after the budget
    dropped_for_budget: list[str]
    tokens_in: int
    tokens_out: int
    model: str
    prompt_sha256: str


@dataclass(frozen=True)
class EntailmentResult:
    verdicts: dict[int, tuple[bool, str]]  # claim number -> (supported, reason)
    tokens_in: int
    tokens_out: int


class GenerationService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.client = GeminiClient(settings)

    @property
    def configured(self) -> bool:
        return self.client.configured

    def draft(self, question: str, sources: list[Source]) -> Draft:
        prompts = load_prompts()
        budget = self._s.context_budget_tokens
        fixed = estimate_tokens(prompts.answer_system) + estimate_tokens(question) + 200
        kept: list[Source] = []
        dropped: list[str] = []
        used = fixed
        for s in sources:
            cost = s.token_count + 40  # chunk text plus its delimiter attributes
            if used + cost > budget:
                dropped.append(s.chunk_id)
            else:
                kept.append(s)
                used += cost
        user = answer_user_prompt(question, kept)
        assert estimate_tokens(prompts.answer_system) + estimate_tokens(user) <= budget + 200
        out = self.client.generate_json(system=prompts.answer_system, user=user, schema=ANSWER_SCHEMA)
        return Draft(out.data, kept, dropped, out.tokens_in, out.tokens_out, out.model, prompts.sha256)

    def entailment(self, claims: list[tuple[int, str, list[str]]], sources: dict[str, Source]) -> EntailmentResult:
        if not claims:
            return EntailmentResult({}, 0, 0)
        prompts = load_prompts()
        out = self.client.generate_json(
            system=prompts.verify_system, user=verify_user_prompt(claims, sources), schema=VERIFY_SCHEMA
        )
        verdicts: dict[int, tuple[bool, str]] = {}
        for item in out.data.get("verdicts") or []:
            if not isinstance(item, dict):
                continue
            try:
                n = int(item.get("claim", 0))
            except TypeError, ValueError:
                continue
            verdicts.setdefault(n, (item.get("supported") is True, str(item.get("reason", ""))[:240]))
        return EntailmentResult(verdicts, out.tokens_in, out.tokens_out)
