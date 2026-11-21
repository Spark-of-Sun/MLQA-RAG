"""Provider-agnostic LLM client, Gemini implementation (blueprint 11.8).

Structured JSON output, timeouts, and a model fallback chain: the configured model (`LLM_MODEL`) first, then
`LLM_FALLBACK_MODELS`. A model that is overloaded (429/503) or times out is skipped for two minutes, so one
busy model does not stall every request. The API key travels in a header and is never logged.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from lmqa_models.settings import Settings

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta"
COOLDOWN_SECONDS = 120
TRANSIENT = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Provider failure. Safe to show: contains no key and no document text."""


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]
    tokens_in: int
    tokens_out: int
    model: str


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0))
        self._down_until: dict[str, float] = {}
        self._no_thinking: set[str] = set()
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._s.gemini_api_key)

    @property
    def model(self) -> str:
        return self._s.llm_model

    def _order(self) -> list[str]:
        now = time.monotonic()
        models = self._s.llm_models
        with self._lock:
            up = [m for m in models if self._down_until.get(m, 0) <= now]
            down = sorted((m for m in models if m not in up), key=lambda m: self._down_until[m])
        return up + down

    def _mark_down(self, model: str) -> None:
        with self._lock:
            self._down_until[model] = time.monotonic() + COOLDOWN_SECONDS

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        if not self._s.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        failures: list[str] = []
        for model in self._order():
            try:
                return self._generate(model, system, user, schema)
            except _Transient as exc:
                log.warning("model %s unavailable (%s); trying the next model", model, exc)
                self._mark_down(model)
                failures.append(f"{model}: {exc}")
        raise LLMError("All configured models are busy right now; try again in a minute. (" + "; ".join(failures) + ")")

    def _generate(self, model: str, system: str, user: str, schema: dict[str, Any]) -> Completion:
        config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "maxOutputTokens": self._s.llm_max_output_tokens,
        }
        if self._s.llm_thinking_level and model not in self._no_thinking:
            config["thinkingConfig"] = {"thinkingLevel": self._s.llm_thinking_level}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        headers = {"x-goog-api-key": self._s.gemini_api_key or "", "content-type": "application/json"}
        try:
            resp = self._client.post(f"{BASE}/models/{model}:generateContent", headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise _Transient("timed out") from exc
        except httpx.HTTPError as exc:
            raise _Transient(type(exc).__name__) from exc
        if resp.status_code in TRANSIENT:
            raise _Transient(f"HTTP {resp.status_code}")
        if resp.status_code == 400 and "thinking" in _message(resp).lower() and "thinkingConfig" in config:
            self._no_thinking.add(model)  # this model does not accept thinkingLevel; retry once without it
            return self._generate(model, system, user, schema)
        if resp.status_code == 404:
            raise _Transient("model not available to this key")
        if resp.status_code != 200:
            raise LLMError(f"Gemini returned {resp.status_code}: {_message(resp)}")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise LLMError(f"Gemini returned no answer ({reason})")
        cand = candidates[0]
        if cand.get("finishReason") not in {None, "STOP"}:
            raise LLMError(f"Gemini stopped early ({cand.get('finishReason')})")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("Gemini returned malformed JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMError("Gemini returned an unexpected JSON shape")
        usage = data.get("usageMetadata") or {}
        return Completion(
            data=parsed,
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
            model=str(data.get("modelVersion") or model),
        )

    def list_models(self) -> list[str]:
        resp = self._client.get(
            f"{BASE}/models", headers={"x-goog-api-key": self._s.gemini_api_key or ""}, params={"pageSize": 200}
        )
        if resp.status_code != 200:
            raise LLMError(f"Gemini returned {resp.status_code}: {_message(resp)}")
        return [m["name"].removeprefix("models/") for m in resp.json().get("models", [])]


class _Transient(Exception):
    pass


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", ""))[:300] or resp.reason_phrase
    except ValueError:
        return resp.reason_phrase
