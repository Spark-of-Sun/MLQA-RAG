"""Answer providers behind one interface (blueprint 11.8 provider boundary).

Three wire protocols cover every supported provider:
  gemini     Google Generative Language API, JSON schema output
  openai     Chat Completions: OpenAI, Groq, OpenRouter, DeepSeek, Mistral, Together, Ollama and any
             OpenAI-compatible server. JSON schema output where the server supports it, else JSON mode with the
             schema in the instructions; the result is validated the same way either way.
  anthropic  Messages API with one forced tool whose input schema is the answer schema.
Each `generate()` returns a `Completion` or raises `_Transient` (try another model) or `LLMError` (fail closed).
API keys travel in headers and are never logged or put into error messages.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from lmqa_models.settings import PROVIDERS, Settings

COOLDOWN_SECONDS = 120
TRANSIENT = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    """Provider failure. Safe to show: contains no key and no document text."""


@dataclass(frozen=True)
class Completion:
    data: dict[str, Any]
    tokens_in: int
    tokens_out: int
    model: str
    key_id: str = ""  # fingerprint of the API key that served the call (never the key)


class _Transient(Exception):
    """This model cannot serve the request now; another may. `cooldown`: how long to skip it.

    `scope` says what is unavailable: "quota" this key's quota for this model (another key may still work),
    "key" the key itself (rejected for every model), "model" the model for everyone (overloaded, not available)."""

    def __init__(
        self,
        reason: str,
        *,
        retry_soon: bool = True,
        cooldown: float = COOLDOWN_SECONDS,
        daily_quota: bool = False,
        scope: str = "model",
    ) -> None:
        super().__init__(reason)
        self.retry_soon = retry_soon
        self.cooldown = cooldown
        self.daily_quota = daily_quota
        self.scope = scope


def json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini-style schema (OBJECT, STRING, propertyOrdering) -> standard JSON Schema, strict-mode ready:
    lower-case types, every object closed (additionalProperties false) with all its properties required."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "propertyOrdering":
            continue
        if key == "type":
            out["type"] = str(value).lower()
        elif key == "properties":
            out["properties"] = {k: json_schema(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = json_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object":
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def parse_json_object(text: str, who: str) -> dict[str, Any]:
    """The JSON object in a model reply; tolerates code fences and stray text around it."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        try:
            parsed = json.loads(cleaned[start : end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        raise LLMError(f"{who} returned malformed JSON")
    return parsed


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.reason_phrase
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message", ""))[:300] or resp.reason_phrase
    if isinstance(err, str):
        return err[:300]
    return resp.reason_phrase


def _common_errors(resp: httpx.Response, who: str) -> None:
    """Map HTTP failures that mean the same thing for every provider."""
    if resp.status_code in {401, 403}:
        # A bad or unauthorised key for this provider: skip it for an hour, other providers may still answer.
        raise _Transient(f"{who} rejected the API key", retry_soon=False, cooldown=3600, scope="key")
    if resp.status_code == 404:
        raise _Transient("model not available to this key", retry_soon=False, cooldown=24 * 3600)
    if resp.status_code in TRANSIENT:
        raise _Transient(f"HTTP {resp.status_code}")


class Provider:
    name: str

    def __init__(self, name: str, settings: Settings, http: httpx.Client) -> None:
        self.name = name
        self._s = settings
        self._http = http
        self._key = settings.llm_key(name)
        self._base = settings.llm_base_url(name)

    @property
    def configured(self) -> bool:
        needs_key = PROVIDERS[self.name]["key"] is not None and self.name != "openai_compatible"
        return bool(self._base) and (bool(self._key) or not needs_key)

    def missing(self) -> str | None:
        """Which setting is missing, by name, or None."""
        if not self._base:
            return "LLM_BASE_URL"
        if not self.configured:
            return str(PROVIDERS[self.name]["key"])
        return None

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        try:
            return self._http.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise _Transient("timed out", retry_soon=False) from exc
        except httpx.HTTPError as exc:
            raise _Transient(type(exc).__name__) from exc

    def generate(
        self, model: str, system: str, user: str, schema: dict[str, Any], key: str | None = None
    ) -> Completion:
        """`key`: the API key to use for this call (key rotation); the provider's configured key if None."""
        raise NotImplementedError


# ------------------------------------------------------------------------------------------------ Gemini
class GeminiProvider(Provider):
    def __init__(self, name: str, settings: Settings, http: httpx.Client) -> None:
        super().__init__(name, settings, http)
        self._no_thinking: set[str] = set()
        self._lock = threading.Lock()

    def generate(
        self, model: str, system: str, user: str, schema: dict[str, Any], key: str | None = None
    ) -> Completion:
        config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "maxOutputTokens": self._s.llm_max_output_tokens,
        }
        if self._s.llm_temperature is not None:
            config["temperature"] = self._s.llm_temperature
        if self._s.llm_thinking_level and model not in self._no_thinking:
            config["thinkingConfig"] = {"thinkingLevel": self._s.llm_thinking_level}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }
        headers = {"x-goog-api-key": key or self._key or "", "content-type": "application/json"}
        resp = self._post(f"{self._base}/models/{model}:generateContent", headers, body)
        if resp.status_code == 429:
            raise _gemini_quota(resp)
        if resp.status_code == 400 and "thinking" in _message(resp).lower() and "thinkingConfig" in config:
            with self._lock:
                self._no_thinking.add(model)  # this model does not accept thinkingLevel; retry once without it
            return self.generate(model, system, user, schema, key)
        _common_errors(resp, "Gemini")
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
        usage = data.get("usageMetadata") or {}
        return Completion(
            data=parse_json_object(text, "Gemini"),
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
            model=str(data.get("modelVersion") or model),
        )

    def list_models(self) -> list[str]:
        resp = self._http.get(
            f"{self._base}/models", headers={"x-goog-api-key": self._key or ""}, params={"pageSize": 200}
        )
        if resp.status_code != 200:
            raise LLMError(f"Gemini returned {resp.status_code}: {_message(resp)}")
        return [m["name"].removeprefix("models/") for m in resp.json().get("models", [])]


def _gemini_quota(resp: httpx.Response) -> _Transient:
    """Classify a 429: a per-day quota skips the model until it resets; a per-minute one only briefly."""
    quota_ids: list[str] = []
    delay = 0.0
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            for violation in detail.get("violations", []) or []:
                quota_ids.append(str(violation.get("quotaId", "")))
            if m := re.fullmatch(r"(\d+(?:\.\d+)?)s", str(detail.get("retryDelay", ""))):
                delay = float(m.group(1))
    except ValueError:
        pass
    if any("perday" in q.lower() for q in quota_ids):
        return _Transient(
            "daily quota used up", retry_soon=False, cooldown=max(delay, 3600), daily_quota=True, scope="quota"
        )
    return _Transient("rate limited", retry_soon=delay <= 5, cooldown=max(min(delay, 300), 30), scope="quota")


# ------------------------------------------------------------------------------------------------ OpenAI-compatible
class OpenAIProvider(Provider):
    """Chat Completions. Learns per model whether the server takes a JSON schema, and remembers it."""

    def __init__(self, name: str, settings: Settings, http: httpx.Client) -> None:
        super().__init__(name, settings, http)
        self._json_mode_only: set[str] = set()
        self._lock = threading.Lock()

    def generate(
        self, model: str, system: str, user: str, schema: dict[str, Any], key: str | None = None
    ) -> Completion:
        strict = json_schema(schema)
        schema_mode = model not in self._json_mode_only
        if schema_mode:
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": strict},
            }
            instructions = system
        else:
            response_format = {"type": "json_object"}
            instructions = (
                f"{system}\n\nReply with one JSON object only, no other text, matching this JSON Schema:\n"
                f"{json.dumps(strict, separators=(',', ':'))}"
            )
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": user}],
            "response_format": response_format,
        }
        # OpenAI's current models want max_completion_tokens; most compatible servers still read max_tokens.
        body["max_completion_tokens" if self.name in {"openai", "groq"} else "max_tokens"] = (
            self._s.llm_max_output_tokens
        )
        if self._s.llm_temperature is not None:
            body["temperature"] = self._s.llm_temperature
        headers = {"content-type": "application/json"}
        if key or self._key:
            headers["authorization"] = f"Bearer {key or self._key}"
        if self.name == "openrouter":
            headers["x-title"] = "LMQA"
        resp = self._post(f"{self._base}/chat/completions", headers, body)
        if resp.status_code in {400, 422} and schema_mode and _rejects_schema(_message(resp)):
            with self._lock:
                self._json_mode_only.add(model)
            return self.generate(model, system, user, schema, key)
        if resp.status_code == 429:
            raise _openai_quota(resp)
        _common_errors(resp, self.name)
        if resp.status_code != 200:
            raise LLMError(f"{self.name} returned {resp.status_code}: {_message(resp)}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"{self.name} returned no answer")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{self.name} stopped early (output token limit)")
        msg = choice.get("message") or {}
        if msg.get("refusal"):
            raise LLMError(f"{self.name} declined to answer")
        content = msg.get("content") or ""
        if isinstance(content, list):  # some servers return content parts
            content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        return Completion(
            data=parse_json_object(str(content), self.name),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model=str(data.get("model") or model),
        )


def _rejects_schema(message: str) -> bool:
    m = message.lower()
    return any(w in m for w in ("response_format", "json_schema", "json schema", "structured output", "schema"))


def _openai_quota(resp: httpx.Response) -> _Transient:
    """429: `insufficient_quota` is a billing limit (skip for an hour); anything else is a short rate limit."""
    try:
        err = resp.json().get("error") or {}
        code = str(err.get("code") or err.get("type") or "") if isinstance(err, dict) else ""
    except ValueError:
        code = ""
    if "insufficient_quota" in code or "quota" in _message(resp).lower():
        return _Transient("quota used up", retry_soon=False, cooldown=3600, daily_quota=True, scope="quota")
    retry = resp.headers.get("retry-after", "")
    delay = float(retry) if retry.replace(".", "", 1).isdigit() else 30.0
    return _Transient("rate limited", retry_soon=delay <= 5, cooldown=max(min(delay, 300), 30), scope="quota")


# ------------------------------------------------------------------------------------------------ Anthropic
class AnthropicProvider(Provider):
    TOOL = "respond"

    def generate(
        self, model: str, system: str, user: str, schema: dict[str, Any], key: str | None = None
    ) -> Completion:
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": self._s.llm_max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": self.TOOL,
                    "description": "Return the response. Always call this tool exactly once.",
                    "input_schema": json_schema(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": self.TOOL},
        }
        if self._s.llm_temperature is not None:
            body["temperature"] = self._s.llm_temperature
        headers = {
            "x-api-key": key or self._key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = self._post(f"{self._base}/messages", headers, body)
        if resp.status_code == 429:
            retry = resp.headers.get("retry-after", "")
            delay = float(retry) if retry.replace(".", "", 1).isdigit() else 30.0
            raise _Transient("rate limited", retry_soon=delay <= 5, cooldown=max(min(delay, 300), 30), scope="quota")
        _common_errors(resp, "Anthropic")
        if resp.status_code != 200:
            raise LLMError(f"Anthropic returned {resp.status_code}: {_message(resp)}")
        data = resp.json()
        if data.get("stop_reason") == "max_tokens":
            raise LLMError("Anthropic stopped early (output token limit)")
        block = next(
            (b for b in data.get("content") or [] if b.get("type") == "tool_use" and b.get("name") == self.TOOL),
            None,
        )
        if block is None or not isinstance(block.get("input"), dict):
            raise LLMError("Anthropic returned no structured answer")
        usage = data.get("usage") or {}
        return Completion(
            data=block["input"],
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            model=str(data.get("model") or model),
        )


KINDS: dict[str, type[Provider]] = {"gemini": GeminiProvider, "openai": OpenAIProvider, "anthropic": AnthropicProvider}


def build_provider(name: str, settings: Settings, http: httpx.Client) -> Provider:
    return KINDS[str(PROVIDERS[name]["kind"])](name, settings, http)
