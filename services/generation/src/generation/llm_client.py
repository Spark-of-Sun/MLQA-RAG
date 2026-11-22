"""Provider-agnostic LLM client with a fallback chain (blueprint 11.8).

The chain is `LLM_PROVIDER` + `LLM_MODEL` first, then `LLM_FALLBACK_MODELS`; a fallback entry is a model of the same
provider, or `provider:model` for another one (for example `groq:llama-3.3-70b-versatile`). A model that is busy
(429/503), times out, is not available, or whose provider rejects the key is skipped for a while, so one failing
model does not stall every request. Providers whose key is not set are left out of the chain.

Key rotation: with several Gemini keys (GEMINI_API_KEYS, one per Google Cloud project, each with its own quota), a
model is tried with every key before the chain moves to the next model. During a question the question's key goes
first (question 1 the first key, question 2 the second, ...: lmqa_models.quota.question); outside one, the key least
used today. A local counter (lmqa_models.quota) tracks each key's requests and tokens per model against the model's
limits, so a key or model that would be refused is skipped without sending anything, and counts the outcome of
every call per key fingerprint and model.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from generation.providers import Completion, GeminiProvider, LLMError, Provider, _Transient, build_provider
from lmqa_models.quota import current_question, fingerprint, rotate
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
        self._quota = settings.quota()

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

    def _keys(self, provider: str) -> list[tuple[str, str | None]]:
        """(fingerprint, key) pairs to try for `provider`, least used today first. Keys never leave this method
        except into the request header."""
        if provider == "gemini":
            keys: list[tuple[str, str | None]] = list(self._s.gemini_keys())
        else:
            key = self._s.llm_key(provider)
            keys = [(fingerprint(key) if key else provider, key)]
        return keys

    def _ordered_keys(self, provider: str, model: str) -> list[tuple[str, str | None]]:
        keys = self._keys(provider)
        if len(keys) < 2:
            return keys
        if (n := current_question()) is not None:
            return rotate(keys, n)
        if self._quota is None:
            return keys
        used = {kid: self._quota.used_today(kid, model) for kid, _ in keys}
        return sorted(keys, key=lambda k: used[k[0]])  # stable: configured order breaks ties

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any]) -> Completion:
        if not self.configured:
            raise LLMError(f"No answer model is configured: set {', '.join(self.missing()) or 'LLM_PROVIDER'}")
        estimate = (len(system) + len(user)) // 4
        failures: dict[tuple[str, str], _Transient] = {}
        for attempt in range(2):
            # Second pass: only models that were momentarily busy, after a short pause.
            entries = self._order() if attempt == 0 else [e for e, f in failures.items() if f.retry_soon]
            if attempt and entries:
                time.sleep(2.5)
            for provider, model in entries:
                label = model_label(provider, model)
                tried = False
                quota_only = True
                daily_everywhere = True
                soonest = float("inf")
                for key_id, key in self._ordered_keys(provider, model):
                    q = self._quota
                    if q is not None and not q.acquire(key_id, model, tokens=estimate):
                        # Known locally to be over a limit: skip without sending a request.
                        q.record(key_id, model, "skipped")
                        wait = q.wait_seconds(key_id, model, tokens=estimate)
                        daily_everywhere = daily_everywhere and wait is None
                        if wait is not None:
                            soonest = min(soonest, wait)
                        continue
                    tried = True
                    try:
                        out = self.providers[provider].generate(model, system, user, schema, key)
                    except _Transient as exc:
                        if q is not None:
                            q.record(key_id, model, _outcome(exc))
                        if exc.scope == "quota":
                            if q is not None:
                                q.block(key_id, model, seconds=exc.cooldown, daily=exc.daily_quota)
                            daily_everywhere = daily_everywhere and exc.daily_quota
                            log.warning("%s on key %s: %s; trying the next key", label, key_id, exc)
                            continue
                        if exc.scope == "key":
                            if q is not None:
                                q.block_key(key_id, exc.cooldown)
                            log.warning("key %s rejected by %s; trying the next key", key_id, provider)
                            continue
                        # The model itself is unavailable (overloaded, timed out, not offered): other keys won't help.
                        quota_only = False
                        log.warning("%s unavailable (%s); trying the next model", label, exc)
                        self._mark_down((provider, model), exc.cooldown)
                        failures[(provider, model)] = exc
                        break
                    except LLMError:
                        if q is not None:
                            q.record(key_id, model, "error")  # e.g. an unusable reply: not retried on another key
                        raise
                    if q is not None:
                        q.record(key_id, model, "ok")
                        q.correct_tokens(key_id, model, estimate, out.tokens_in)
                    log.debug("%s answered on key %s", label, key_id)
                    return Completion(out.data, out.tokens_in, out.tokens_out, model_label(provider, out.model), key_id)
                else:
                    if quota_only:
                        reason = "daily quota used up on every key" if daily_everywhere else "rate limit on every key"
                        if not tried:
                            log.info("%s skipped without a request: %s (local count)", label, reason)
                        # A per-minute limit that frees up within seconds is worth the second pass.
                        failures[(provider, model)] = _Transient(
                            reason, retry_soon=soonest <= 3, daily_quota=daily_everywhere, scope="quota"
                        )
        if failures and all(f.daily_quota for f in failures.values()):
            raise LLMError(
                "The daily quota is used up for every configured model and key (it resets at midnight Pacific "
                "time). Add a key from another project to GEMINI_API_KEYS, enable billing, or add a model or "
                "provider to LLM_FALLBACK_MODELS."
            )
        detail = "; ".join(f"{model_label(*e)}: {f}" for e, f in failures.items())
        raise LLMError(f"All configured models are unavailable right now; try again in a minute. ({detail})")


def _outcome(exc: _Transient) -> str:
    """The recorded outcome of a call the provider refused or could not serve."""
    if exc.scope == "quota":
        return "daily_quota" if exc.daily_quota else "rate_limited"
    if exc.scope == "key":
        return "key_rejected"
    return "timeout" if "timed out" in str(exc) else "unavailable"  # overloaded (503), not offered, unreachable
