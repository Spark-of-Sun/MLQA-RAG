"""Plan the search, draft answers, check entailment (blueprint 11.3 to 11.6).

`plan_query()` turns a follow-up ("and section 304?") into a standalone question using the last few turns of the
conversation, and writes up to three alternative phrasings in the documents' likely vocabulary (query expansion);
retrieval searches with all of them and fuses the results. `draft()` enforces the hard token budget before any
provider call (11.4): earlier turns are included only to interpret the question, and sources are admitted whole, in
rank order, until the budget is reached. The model sees request-local aliases only. `entailment()` is the MVP
stand-in for the pinned NLI model (V6, see docs/mvp.md): a strict second pass that can only remove sentences, never
approve a rejected one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from generation.llm_client import LLMClient, LLMError
from generation.prompts import (
    ANSWER_SCHEMA,
    QUERY_SCHEMA,
    VERIFY_SCHEMA,
    Turn,
    answer_user_prompt,
    estimate_tokens,
    load_prompts,
    query_user_prompt,
    verify_user_prompt,
)
from generation.rerank import LLMReranker
from lmqa_models.rag import Source
from lmqa_models.settings import LLM_RERANK, Settings

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
    key_id: str = ""


MAX_ALTERNATIVES = 4  # the planner writes four queries: plain, legal terms, section numbers, related provisions


@dataclass(frozen=True)
class QueryPlan:
    question: str  # the standalone question: what is searched first and what the answer must address
    alternatives: list[str]  # other phrasings, searched with a lower weight
    tokens_in: int
    tokens_out: int
    model: str = ""
    key_id: str = ""
    detail_note: str = ""  # a detail removed from the question that the answer should say is not covered


@dataclass(frozen=True)
class EntailmentResult:
    verdicts: dict[int, tuple[bool, str]]  # claim number -> (supported, reason)
    tokens_in: int
    tokens_out: int
    model: str = ""
    key_id: str = ""


class GenerationService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.client = LLMClient(settings)
        # Query planning has its own chain (QUERY_MODEL, QUERY_FALLBACK_MODELS, then the answer chain), so this short
        # task runs on high-quota models and leaves the strong models' daily quota for answers.
        planner = settings.planner_settings()
        self.planner = LLMClient(planner) if planner is not None else self.client
        # RERANK_MODEL=llm: passages are scored by the answer models, weakest first; the gateway hands this to
        # retrieval (which imports no LLM client).
        self.reranker = LLMReranker(settings) if settings.rerank_model == LLM_RERANK else None

    @property
    def configured(self) -> bool:
        return self.client.configured

    def plan_query(self, history: list[Turn], question: str, *, expand: bool) -> QueryPlan:
        """Standalone question and alternatives. Falls back to the question as asked if the model is unavailable or
        its output is unusable: planning improves recall but is never required for an answer."""
        if not history and not expand:
            return QueryPlan(question, [], 0, 0)
        prompts = load_prompts()
        try:
            out = self.planner.generate_json(
                system=prompts.query_system,
                user=query_user_prompt(history[-MAX_HISTORY_TURNS:], question),
                schema=QUERY_SCHEMA,
            )
        except LLMError as exc:
            log.warning("query planning unavailable (%s); searching with the question as asked", exc)
            return QueryPlan(question, [], 0, 0)
        # The corrected question (references resolved, spelling fixed, incidental details removed) is searched first;
        # the original question still goes to the answer model, with the note naming any detail that was removed.
        rewritten = " ".join(str(out.data.get("corrected_question", "")).split())
        standalone = rewritten if 3 <= len(rewritten) <= 1000 else question
        note = " ".join(str(out.data.get("keep_detail_note", "")).split())[:300]
        alternatives: list[str] = []
        if expand:
            seen = {standalone.casefold()}
            for item in out.data.get("queries") or []:
                alt = " ".join(str(item).split())
                if 3 <= len(alt) <= 500 and alt.casefold() not in seen:
                    seen.add(alt.casefold())
                    alternatives.append(alt)
        return QueryPlan(
            standalone, alternatives[:MAX_ALTERNATIVES], out.tokens_in, out.tokens_out, out.model, out.key_id, note
        )

    def draft(
        self,
        question: str,
        sources: list[Source],
        *,
        history: list[Turn] | None = None,
        standalone: str | None = None,
        detail_note: str = "",
    ) -> Draft:
        prompts = load_prompts()
        budget = self._s.context_budget_tokens
        recent = (history or [])[-MAX_HISTORY_TURNS:]
        history_cost = sum(estimate_tokens(t.question) + min(estimate_tokens(t.answer), 250) for t in recent)
        fixed = (
            (estimate_tokens(prompts.answer_system) + estimate_tokens(question) + estimate_tokens(detail_note))
            + history_cost
            + 250
        )
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
        user = answer_user_prompt(question, kept, recent, standalone, detail_note)
        assert estimate_tokens(prompts.answer_system) + estimate_tokens(user) <= budget + 300
        out = self.client.generate_json(system=prompts.answer_system, user=user, schema=ANSWER_SCHEMA)
        return Draft(out.data, kept, dropped, out.tokens_in, out.tokens_out, out.model, prompts.sha256, out.key_id)

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
        return EntailmentResult(verdicts, out.tokens_in, out.tokens_out, out.model, out.key_id)
