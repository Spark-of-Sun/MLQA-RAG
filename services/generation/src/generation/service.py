"""Condense follow-ups, draft answers, check entailment (blueprint 11.4 to 11.6).

`condense()` turns a follow-up ("and section 304?") into a standalone question for retrieval, using the last few
turns of the conversation. `draft()` enforces the hard token budget before any provider call (11.4): earlier turns
are included only to interpret the question, and sources are admitted whole, in rank order, until the budget is
reached. The model sees request-local aliases only. `entailment()` is the MVP stand-in for the pinned NLI model
(V6, see docs/mvp.md): a strict second pass that can only remove sentences, never approve a rejected one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from generation.llm_client import LLMClient, LLMError
from generation.prompts import (
    ANSWER_SCHEMA,
    CONDENSE_SCHEMA,
    VERIFY_SCHEMA,
    Turn,
    answer_user_prompt,
    condense_user_prompt,
    estimate_tokens,
    load_prompts,
    verify_user_prompt,
)
from lmqa_models.rag import Source
from lmqa_models.settings import Settings

log = logging.getLogger(__name__)
MAX_HISTORY_TURNS = 4


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
class Condensed:
    question: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class EntailmentResult:
    verdicts: dict[int, tuple[bool, str]]  # claim number -> (supported, reason)
    tokens_in: int
    tokens_out: int


class GenerationService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.client = LLMClient(settings)

    @property
    def configured(self) -> bool:
        return self.client.configured

    def condense(self, history: list[Turn], question: str) -> Condensed:
        """Standalone form of a follow-up. Falls back to the question itself if the rewrite is unusable."""
        if not history:
            return Condensed(question, 0, 0)
        prompts = load_prompts()
        try:
            out = self.client.generate_json(
                system=prompts.condense_system,
                user=condense_user_prompt(history[-MAX_HISTORY_TURNS:], question),
                schema=CONDENSE_SCHEMA,
            )
        except LLMError as exc:
            log.warning("follow-up rewrite unavailable (%s); searching with the question as asked", exc)
            return Condensed(question, 0, 0)
        rewritten = " ".join(str(out.data.get("standalone_question", "")).split())
        if not 3 <= len(rewritten) <= 1000:
            rewritten = question
        return Condensed(rewritten, out.tokens_in, out.tokens_out)

    def draft(
        self, question: str, sources: list[Source], *, history: list[Turn] | None = None, standalone: str | None = None
    ) -> Draft:
        prompts = load_prompts()
        budget = self._s.context_budget_tokens
        recent = (history or [])[-MAX_HISTORY_TURNS:]
        history_cost = sum(estimate_tokens(t.question) + min(estimate_tokens(t.answer), 250) for t in recent)
        fixed = estimate_tokens(prompts.answer_system) + estimate_tokens(question) + history_cost + 250
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
        user = answer_user_prompt(question, kept, recent, standalone)
        assert estimate_tokens(prompts.answer_system) + estimate_tokens(user) <= budget + 300
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
