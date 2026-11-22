"""Gemini embeddings (768 dimensions, unit length). The API key travels in a header and is never logged.

Every request uses the first key (GEMINI_API_KEYS, one per Google Cloud project) that the local counter
(lmqa_models.quota) says still has room, so a request the provider would refuse is not sent. During a question the
question's key is tried first (key rotation per question); otherwise the key least used today. All keys are used for
a model before a caller moves to the next model. Each request's outcome is counted per key fingerprint and model.

Several embedding models can be configured (GEMINI_EMBEDDING_MODEL, then GEMINI_EMBEDDING_FALLBACK_MODELS), each
with its own daily quota. Vectors from different models are not comparable, so callers always say which model to
use: ingestion embeds a whole document with one model, and search embeds the question with each model in use. A
model whose daily quota is used up, or that rejects requests, is skipped for an hour.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import OrderedDict

import httpx

from lmqa_models.quota import current_question, rotate
from lmqa_models.settings import EMBEDDING_DIM, Settings

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta"
BATCH = 50
MAX_CHARS = 8000
QUERY_CACHE_SIZE = 512
DOWN_SECONDS = 3600


class EmbeddingError(RuntimeError):
    """Embedding failed. The message contains no key and no document text."""


class QuotaExhausted(EmbeddingError):
    """The model's daily quota is used up; another model may still have quota."""


class Embedder:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        self._query_cache: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._down_until: dict[str, float] = {}
        self._quota = settings.quota()

    @property
    def configured(self) -> bool:
        return bool(self._s.gemini_api_keys)

    @property
    def model(self) -> str:
        """The primary model."""
        return self._s.embedding_model

    @property
    def models(self) -> list[str]:
        return self._s.embedding_models

    def available(self) -> list[str]:
        """Configured models not currently skipped, in preference order."""
        now = time.monotonic()
        with self._lock:
            return [m for m in self.models if self._down_until.get(m, 0) <= now]

    def mark_down(self, model: str, seconds: float = DOWN_SECONDS) -> None:
        with self._lock:
            self._down_until[model] = time.monotonic() + seconds

    def embed_documents(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        # Indexing runs in the background: wait out per-minute quotas for up to 20 minutes per document.
        return self._embed(texts, "RETRIEVAL_DOCUMENT", model or self.model, budget_seconds=20 * 60)

    def embed_query(self, text: str, model: str | None = None) -> list[float]:
        return self.embed_queries([text], model)[0]

    def embed_queries(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Several phrasings of one question in one request. A person is waiting: give up quickly, fail closed.
        Recent query vectors are kept in memory (a repeated or re-phrased question is common); never passages."""
        model = model or self.model
        with self._lock:
            found = {t: self._query_cache[(model, t)] for t in texts if (model, t) in self._query_cache}
        missing = [t for t in dict.fromkeys(texts) if t not in found]
        if missing:
            fresh = self._embed(missing, "RETRIEVAL_QUERY", model, budget_seconds=25)
            found.update(zip(missing, fresh, strict=True))
            with self._lock:
                for t, v in zip(missing, fresh, strict=True):
                    self._query_cache[(model, t)] = v
                while len(self._query_cache) > QUERY_CACHE_SIZE:
                    self._query_cache.popitem(last=False)
        return [found[t] for t in texts]

    def _embed(self, texts: list[str], task: str, model_name: str, *, budget_seconds: float) -> list[list[float]]:
        if not self._s.gemini_api_keys:
            raise EmbeddingError("GEMINI_API_KEY is not set")
        model = f"models/{model_name}"
        deadline = time.monotonic() + budget_seconds
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start : start + BATCH]
            body = {
                "requests": [
                    {
                        "model": model,
                        "content": {"parts": [{"text": t[:MAX_CHARS]}]},
                        "taskType": task,
                        "outputDimensionality": EMBEDDING_DIM,
                    }
                    for t in batch
                ]
            }
            tokens = sum(len(t[:MAX_CHARS]) for t in batch) // 4
            data = self._post(model_name, f"{model}:batchEmbedContents", body, len(batch), tokens, deadline)
            items = data.get("embeddings") or []
            if len(items) != len(batch):
                raise EmbeddingError("wrong number of embeddings returned")
            for item in items:
                values = [float(v) for v in item.get("values", [])]
                if len(values) != EMBEDDING_DIM:
                    raise EmbeddingError(f"embedding has {len(values)} dimensions, expected {EMBEDDING_DIM}")
                norm = math.sqrt(sum(v * v for v in values)) or 1.0
                out.append([v / norm for v in values])
            if len(texts) > BATCH:
                log.info("embedded %d of %d passages", min(start + BATCH, len(texts)), len(texts))
        return out

    def _ordered_keys(self, model: str) -> list[tuple[str, str]]:
        """Every key for this model: during a question the question's key first (lmqa_models.quota.question),
        otherwise the least used today. The model's quota on all projects is used before the caller moves on."""
        keys = self._s.gemini_keys()
        q = self._quota
        if len(keys) < 2:
            return keys
        if (n := current_question()) is not None:
            return rotate(keys, n)
        if q is None:
            return keys
        return sorted(keys, key=lambda k: q.used_today(k[0], model))

    def _post(
        self, model: str, path: str, body: dict[str, object], items: int, tokens: int, deadline: float
    ) -> dict[str, object]:
        """One batch request on the first key with room for it. Each passage counts as one request toward the
        model's per-minute and per-day limits, so the local counter reserves `items` requests and `tokens`."""
        delay = 2.0
        q = self._quota
        while True:
            soonest: float | None = None
            for key_id, key in self._ordered_keys(model):
                if q is not None and not q.acquire(key_id, model, requests=items, tokens=tokens):
                    q.record(key_id, model, "skipped")
                    wait = q.wait_seconds(key_id, model, requests=items, tokens=tokens)
                    if wait is not None:
                        soonest = wait if soonest is None else min(soonest, wait)
                    continue
                headers = {"x-goog-api-key": key, "content-type": "application/json"}
                try:
                    resp = self._client.post(f"{BASE}/{path}", headers=headers, json=body)
                except httpx.HTTPError as exc:
                    if q is not None:
                        q.record(key_id, model, "timeout" if isinstance(exc, httpx.TimeoutException) else "unavailable")
                    if time.monotonic() + delay > deadline:
                        raise EmbeddingError(f"Gemini unreachable ({type(exc).__name__})") from exc
                    soonest = delay if soonest is None else min(soonest, delay)
                    delay = min(delay * 2, 30)
                    break
                if q is not None:
                    q.record(key_id, model, _outcome(resp))
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    daily = _daily_quota(resp)
                    retry = _retry_delay(resp) or 30.0
                    if q is not None:
                        q.block(key_id, model, seconds=retry, daily=daily)
                    log.warning(
                        "embedding with %s on key %s: %s; trying the next key",
                        model,
                        key_id,
                        "daily quota used up" if daily else "rate limited",
                    )
                    if not daily:
                        soonest = retry if soonest is None else min(soonest, retry)
                    continue
                if resp.status_code in {401, 403}:
                    if q is not None:
                        q.block_key(key_id, 3600)
                    log.warning("key %s rejected for embeddings; trying the next key", key_id)
                    continue
                if resp.status_code in {500, 502, 503, 504}:
                    soonest = delay if soonest is None else min(soonest, delay)
                    delay = min(delay * 2, 30)
                    log.warning("embedding with %s returned %d; retrying", model, resp.status_code)
                    break
                raise EmbeddingError(f"Gemini embeddings returned {resp.status_code}: {_message(resp)}")
            if soonest is None:
                raise QuotaExhausted(
                    f"the daily quota of {model} is used up on every key; it resets at midnight Pacific time, or add "
                    "a key from another project to GEMINI_API_KEYS"
                )
            if time.monotonic() + soonest > deadline:
                raise EmbeddingError(f"{model} is rate limited on every key; try again in a minute")
            log.info("embedding with %s: every key is at its per-minute limit; waiting %.0fs", model, soonest)
            time.sleep(soonest)


def _outcome(resp: httpx.Response) -> str:
    """The recorded outcome of one embedding request (the same names as the answer models use)."""
    if resp.status_code == 200:
        return "ok"
    if resp.status_code == 429:
        return "daily_quota" if _daily_quota(resp) else "rate_limited"
    if resp.status_code in {401, 403}:
        return "key_rejected"
    return "unavailable" if resp.status_code in {500, 502, 503, 504} else "error"


def _daily_quota(resp: httpx.Response) -> bool:
    """True when the 429 is a per-day quota (waiting minutes will not help)."""
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            for violation in detail.get("violations", []) or []:
                if "perday" in str(violation.get("quotaId", "")).lower():
                    return True
    except ValueError:
        return False
    return False


def _message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", ""))[:300] or resp.reason_phrase
    except ValueError:
        return resp.reason_phrase


def _retry_delay(resp: httpx.Response) -> float | None:
    """Honour the server's RetryInfo (for example "retryDelay": "17s") on quota errors, capped at 60 s."""
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(detail.get("retryDelay", "")))
            if m:
                return min(float(m.group(1)) + 1, 60.0)
    except ValueError:
        return None
    return None
