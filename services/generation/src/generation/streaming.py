"""Streaming generation for sentence-gated delivery (blueprint 11.4, 11.6, G6.1, G6.2, G6.10).

The model writes plain sentences with inline citation tags (`[S1][S3]`) instead of one JSON object, so the
validator can judge and release sentence by sentence. `stream_answer` yields text deltas from the first model in
the chain that accepts the request; once a model has produced output it is never swapped mid-answer (a second
model would start a different answer). Cancellation (`cancel` set by the gateway when the client disconnects or the
principal is revoked) closes the provider connection at once, which stops the provider's work and its billing.

The prompt is assembled within a hard token budget: chunks are kept or dropped whole, never cut, and every dropped
chunk is reported with its reason (G6.2).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from generation.prompts import Turn, answer_user_prompt, estimate_tokens, load_prompts
from lmqa_models.envfile import ROOT
from lmqa_models.rag import Source
from lmqa_models.settings import PROVIDERS, Settings

STREAM_TEMPLATE = ROOT / "prompts" / "templates" / "answer_stream.md"
DELIMITER_COST = 40
SAFETY_MARGIN = 300


class StreamError(RuntimeError):
    pass


@dataclass
class BudgetedPrompt:
    system: str
    user: str
    kept: list[Source]
    dropped: list[tuple[str, str]]  # (chunk_id, reason)
    tokens: int
    prompt_sha256: str


@dataclass
class StreamState:
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)


def budget_prompt(
    settings: Settings,
    question: str,
    sources: list[Source],
    *,
    history: list[Turn] | None = None,
    standalone: str | None = None,
) -> BudgetedPrompt:
    prompts = load_prompts()
    system = (
        STREAM_TEMPLATE.read_text(encoding="utf-8")
        if STREAM_TEMPLATE.is_file()
        else prompts.answer_system
    )
    budget = settings.context_budget_tokens
    recent = (history or [])[-4:]
    fixed = (
        estimate_tokens(system)
        + estimate_tokens(question)
        + SAFETY_MARGIN
        + sum(estimate_tokens(t.question) + min(estimate_tokens(t.answer), 250) for t in recent)
    )
    kept: list[Source] = []
    dropped: list[tuple[str, str]] = []
    used = fixed
    for s in sources:
        cost = s.token_count + DELIMITER_COST
        if used + cost > budget:
            dropped.append((s.chunk_id, "token_budget"))
            continue
        kept.append(s)
        used += cost
    user = answer_user_prompt(question, kept, recent, standalone, "")
    total = estimate_tokens(system) + estimate_tokens(user)
    if total > budget + SAFETY_MARGIN:
        raise StreamError(
            "assembled prompt exceeds the token budget"
        )  # invariant G6.1, never expected
    return BudgetedPrompt(system, user, kept, dropped, total, prompts.sha256)


def _gemini(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
    http: httpx.Client,
    base: str,
    key: str,
    model: str,
    p: BudgetedPrompt,
    s: Settings,
    state: StreamState,
) -> Iterator[str]:
    body = {
        "systemInstruction": {"parts": [{"text": p.system}]},
        "contents": [{"role": "user", "parts": [{"text": p.user}]}],
        "generationConfig": {"maxOutputTokens": s.llm_max_output_tokens, "temperature": 0},
    }
    url = f"{base}/models/{model}:streamGenerateContent?alt=sse"
    with http.stream("POST", url, json=body, headers={"x-goog-api-key": key}) as resp:
        if resp.status_code != 200:
            raise StreamError(f"{model}: HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if state.cancel.is_set():
                return
            if not line.startswith("data:"):
                continue
            chunk = json.loads(line[5:])
            usage = chunk.get("usageMetadata") or {}
            state.tokens_in = int(usage.get("promptTokenCount", state.tokens_in))
            state.tokens_out = int(usage.get("candidatesTokenCount", state.tokens_out))
            for cand in chunk.get("candidates", [])[:1]:
                for part in (cand.get("content") or {}).get("parts", []):
                    if part.get("text") and not part.get("thought"):
                        yield part["text"]


def _openai(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
    http: httpx.Client,
    base: str,
    key: str | None,
    model: str,
    p: BudgetedPrompt,
    s: Settings,
    state: StreamState,
) -> Iterator[str]:
    body = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": s.llm_max_output_tokens,
        "temperature": 0,
        "messages": [{"role": "system", "content": p.system}, {"role": "user", "content": p.user}],
    }
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with http.stream("POST", f"{base}/chat/completions", json=body, headers=headers) as resp:
        if resp.status_code != 200:
            raise StreamError(f"{model}: HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if state.cancel.is_set():
                return
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            chunk = json.loads(line[5:])
            if usage := chunk.get("usage"):
                state.tokens_in, state.tokens_out = (
                    int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)),
                )
            for choice in chunk.get("choices", [])[:1]:
                if text := (choice.get("delta") or {}).get("content"):
                    yield text


def _anthropic(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
    http: httpx.Client,
    base: str,
    key: str | None,
    model: str,
    p: BudgetedPrompt,
    s: Settings,
    state: StreamState,
) -> Iterator[str]:
    body = {
        "model": model,
        "stream": True,
        "max_tokens": s.llm_max_output_tokens,
        "temperature": 0,
        "system": p.system,
        "messages": [{"role": "user", "content": p.user}],
    }
    headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    with http.stream("POST", f"{base}/messages", json=body, headers=headers) as resp:
        if resp.status_code != 200:
            raise StreamError(f"{model}: HTTP {resp.status_code}")
        for line in resp.iter_lines():
            if state.cancel.is_set():
                return
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event.get("type") == "message_start":
                state.tokens_in = int(event["message"]["usage"].get("input_tokens", 0))
            elif (
                event.get("type") == "content_block_delta"
                and event["delta"].get("type") == "text_delta"
            ):
                yield event["delta"]["text"]
            elif event.get("type") == "message_delta":
                state.tokens_out = int(
                    (event.get("usage") or {}).get("output_tokens", state.tokens_out)
                )


def stream_answer(settings: Settings, prompt: BudgetedPrompt, state: StreamState) -> Iterator[str]:
    """Yield deltas from the first model in the chain that answers; StreamError when none does."""
    errors: list[str] = []
    timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10.0)
    with httpx.Client(timeout=timeout) as http:
        for provider, model in settings.llm_chain:
            kind = PROVIDERS.get(provider, {}).get("kind")
            base = settings.llm_base_url(provider)
            key = settings.llm_key(provider)
            if not base or (PROVIDERS[provider].get("key") and not key):
                continue
            fn = {"gemini": _gemini, "openai": _openai, "anthropic": _anthropic}.get(str(kind))
            if fn is None:
                continue
            produced = False
            try:
                for delta in fn(http, base, key, model, prompt, settings, state):  # type: ignore[arg-type]
                    if not produced:
                        state.model = model if provider == "gemini" else f"{provider}:{model}"
                        produced = True
                    yield delta
                if produced:
                    return
            except (StreamError, httpx.HTTPError, json.JSONDecodeError) as exc:
                if produced:
                    raise StreamError(f"{model} failed mid-answer") from exc
                errors.append(str(exc))
    raise StreamError("no answer model accepted the request: " + "; ".join(errors[-3:]))
