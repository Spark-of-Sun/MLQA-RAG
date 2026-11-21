"""Provider-agnostic LLM client with a fallback chain (blueprint 11.8).

The chain is `LLM_PROVIDER` + `LLM_MODEL` first, then `LLM_FALLBACK_MODELS`; a fallback entry is a model of the same
provider, or `provider:model` for another one (for example `groq:llama-3.3-70b-versatile`). A model that is busy
(429/503), times out, is not available, or whose provider rejects the key is skipped for a while, so one failing
model does not stall every request. Providers whose key is not set are left out of the chain.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from generation.providers import Completion, GeminiProvider, LLMError, Provider, _Transient, build_provider
from lmqa_models.settings import Settings, model_label

log = logging.getLogger(__name__)

__all__ = ["Completion", "LLMClient", "LLMError"]


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._http = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0))
        self.providers: dict[str, Provider] = {
            p: build_provider(p, settings, self._http) for p in dict.fromkeys(p for p, _ in settings.llm_chain)
        }
        self._down_until: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    @property
    def chain(self) -> list[tuple[str, str]]:
        """The usable chain: entries whose provider has its key (and endpoint) set."""
        return [(p, m) for p, m in self._s.llm_chain if self.providers[p].configured]

    @property
    def configured(self) -> bool:
        return bool(self.chain)

    @property
    def model(self) -> str:
        """The primary model's label (recorded when no model was called, e.g. nothing was retrieved)."""
        chain = self.chain
        return model_label(*chain[0]) if chain else model_label(self._s.llm_provider, self._s.llm_model or "unset")

    def missing(self) -> list[str]:
        """Names of the settings that keep chain entries out, for doctor and error messages."""
        out = [] if self._s.llm_model else ["LLM_MODEL"]
        return out + sorted({m for p in self.providers.values() if (m := p.missing())})

    def gemini(self) -> GeminiProvider | None:
        p = self.providers.get("gemini")
        return p if isinstance(p, GeminiProvider) else None

    def _order(self) -> list[tuple[str, str]]:
        now = time.monotonic()
        chain = self.chain
        with self._lock:
            up = [e for e in chain if self._down_until.get(e, 0) <= now]
            down = sorted((e for e in chain if e not in up), key=lambda e: self._down_until[e])
        return up + down

    def _mark_down(self, entry: tuple[str, str], seconds: float) -> None:
        with self._lock:
            self._down_until[entry] = time.monotonic() + seconds

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        if not self.configured:
            raise LLMError(f"No answer model is configured: set {', '.join(self.missing()) or 'LLM_PROVIDER'}")
        failures: dict[tuple[str, str], _Transient] = {}
        for attempt in range(2):
            # Second pass: only models that were momentarily busy, after a short pause.
            entries = self._order() if attempt == 0 else [e for e, f in failures.items() if f.retry_soon]
            if attempt and entries:
                time.sleep(2.5)
            for provider, model in entries:
                try:
                    out = self.providers[provider].generate(model, system, user, schema)
                except _Transient as exc:
                    log.warning("%s unavailable (%s); trying the next model", model_label(provider, model), exc)
                    self._mark_down((provider, model), exc.cooldown)
                    failures[(provider, model)] = exc
                    continue
                return Completion(out.data, out.tokens_in, out.tokens_out, model_label(provider, out.model))
        if failures and all(f.daily_quota for f in failures.values()):
            hours = min(f.cooldown for f in failures.values()) / 3600
            raise LLMError(
                f"The quota is used up for every configured model (resets in about {hours:.0f} h). Enable billing "
                "with your provider, or add a model or provider to LLM_FALLBACK_MODELS."
            )
        detail = "; ".join(f"{model_label(*e)}: {f}" for e, f in failures.items())
        raise LLMError(f"All configured models are unavailable right now; try again in a minute. ({detail})")
