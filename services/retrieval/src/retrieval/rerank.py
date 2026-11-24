"""Cross-encoder re-ranking (blueprint 11.3 step 4).

Fused hybrid search is good at recall and poor at precision: it ranks by rank positions, not by whether a passage
answers the question. A cross-encoder reads the question and each passage together and scores relevance directly,
which is the standard second stage of production retrieval. Scores are logits; `sigmoid` turns them into a 0-1
relevance probability so one threshold (RERANK_MIN_SCORE) works across models.

The model runs locally (ONNX Runtime through fastembed); no passage text leaves the machine for this step. It is
loaded once, in the background at startup, and shared by all requests.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import TYPE_CHECKING, Protocol

from lmqa_models.rag import RerankError

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["PassageScorer", "RerankError", "Reranker", "sigmoid"]


class PassageScorer(Protocol):
    """What retrieval needs from a re-ranker: the local cross-encoder below, or one injected by the gateway (the LLM
    re-ranker in generation, RERANK_MODEL=llm), so this package never imports an LLM client."""

    model: str
    local: bool

    def warm(self) -> None: ...

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance (0-1) of each passage for the query, in input order. Raises RerankError."""
        ...


class Reranker:
    local = True

    def __init__(self, model: str, cache_dir: Path) -> None:
        self.model = model
        self._cache_dir = cache_dir
        self._encoder: object | None = None
        self._load_lock = threading.Lock()
        self._run_lock = (
            threading.Lock()
        )  # one inference at a time: the ONNX session already uses every core

    def warm(self) -> None:
        """Load the model in a background thread so the first question does not wait for it."""
        threading.Thread(target=self._safe_load, name="rerank-load", daemon=True).start()

    def _safe_load(self) -> None:
        try:
            self._load()
        except RerankError as exc:
            log.warning("%s", exc)

    def _load(self) -> object:
        with self._load_lock:
            if self._encoder is None:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    log.info("loading re-ranker %s (first run downloads it)", self.model)
                    self._encoder = TextCrossEncoder(
                        model_name=self.model, cache_dir=str(self._cache_dir)
                    )
                except Exception as exc:  # unknown model name, download failure, broken cache
                    raise RerankError(
                        f"re-ranker {self.model} could not be loaded ({type(exc).__name__})"
                    ) from exc
            return self._encoder

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance probability (0-1) of each passage for the query, in input order."""
        if not passages:
            return []
        encoder = self._load()
        with self._run_lock:
            try:
                logits = list(encoder.rerank(query, passages, batch_size=16))  # type: ignore[attr-defined]
            except Exception as exc:
                raise RerankError(f"re-ranking failed ({type(exc).__name__})") from exc
        return [sigmoid(float(x)) for x in logits]


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)
