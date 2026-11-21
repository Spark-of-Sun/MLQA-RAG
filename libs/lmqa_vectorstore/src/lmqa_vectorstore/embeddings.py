"""Gemini embeddings (768 dimensions, unit length). The API key travels in a header and is never logged."""

from __future__ import annotations

import logging
import math
import re
import time

import httpx

from lmqa_models.settings import EMBEDDING_DIM, Settings

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta"
BATCH = 50
MAX_CHARS = 8000


class EmbeddingError(RuntimeError):
    """Embedding failed. The message contains no key and no document text."""


class Embedder:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))

    @property
    def configured(self) -> bool:
        return bool(self._s.gemini_api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Indexing runs in the background: wait out per-minute quotas for up to 20 minutes per document.
        return self._embed(texts, "RETRIEVAL_DOCUMENT", budget_seconds=20 * 60)

    def embed_query(self, text: str) -> list[float]:
        # A person is waiting: give up quickly and fail closed.
        return self._embed([text], "RETRIEVAL_QUERY", budget_seconds=25)[0]

    def _embed(self, texts: list[str], task: str, *, budget_seconds: float) -> list[list[float]]:
        if not self._s.gemini_api_key:
            raise EmbeddingError("GEMINI_API_KEY is not set")
        model = f"models/{self._s.embedding_model}"
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
            data = self._post(f"{model}:batchEmbedContents", body, deadline)
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

    def _post(self, path: str, body: dict[str, object], deadline: float) -> dict[str, object]:
        headers = {"x-goog-api-key": self._s.gemini_api_key or "", "content-type": "application/json"}
        delay = 2.0
        while True:
            try:
                resp = self._client.post(f"{BASE}/{path}", headers=headers, json=body)
            except httpx.HTTPError as exc:
                if time.monotonic() + delay > deadline:
                    raise EmbeddingError(f"Gemini unreachable ({type(exc).__name__})") from exc
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 and _daily_quota(resp):
                raise EmbeddingError(
                    "the daily Gemini embedding quota for this API key is used up; indexing works again after "
                    "it resets, or enable billing in Google AI Studio for higher limits"
                )
            if resp.status_code in {429, 500, 502, 503, 504}:
                wait = _retry_delay(resp) or delay
                if time.monotonic() + wait > deadline:
                    reason = "rate limit" if resp.status_code == 429 else f"HTTP {resp.status_code}"
                    raise EmbeddingError(f"Gemini embeddings kept failing ({reason}); try again in a few minutes")
                what = "per-minute rate limit reached" if resp.status_code == 429 else f"returned {resp.status_code}"
                log.warning("embedding %s; waiting %.0fs as Gemini asks, then continuing", what, wait)
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            raise EmbeddingError(f"Gemini embeddings returned {resp.status_code}: {_message(resp)}")


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
