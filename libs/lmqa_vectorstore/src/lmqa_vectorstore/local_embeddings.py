"""Local embeddings (EMBEDDING_PROVIDER=local): ONNX Runtime through fastembed, 768 dimensions, unit length.

No passage or question text leaves the machine for this step, and no quota applies. The model is downloaded once
into MODEL_CACHE_DIR (HF_TOKEN, if set, avoids download rate limits) and loaded once per process, shared by
ingestion and retrieval. Same interface as the Gemini `Embedder`, so callers do not know which one they have.

Retrieval models are trained with an instruction on the query side (and some on the passage side); the prefixes
below are the ones each model card asks for. Vectors are stored with the model's name (chunks.embedding_model), so
passages embedded by Gemini earlier are simply not compared with local query vectors.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from lmqa_models.settings import EMBEDDING_DIM, Settings
from lmqa_vectorstore.embeddings import Embedder, EmbeddingError

log = logging.getLogger(__name__)
BATCH = 16
MAX_CHARS = 8000
QUERY_CACHE_SIZE = 512

_BGE_QUERY = "Represent this sentence for searching relevant passages: "
# (model name prefix, query prefix, passage prefix)
_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("baai/bge-", _BGE_QUERY, ""),
    ("snowflake/snowflake-arctic-embed", _BGE_QUERY, ""),
    ("nomic-ai/nomic-embed-text", "search_query: ", "search_document: "),
)

_models_lock = threading.Lock()
_loaded: dict[tuple[str, str], object] = {}


def _prefixes(model: str) -> tuple[str, str]:
    name = model.lower()
    for start, query, passage in _PREFIXES:
        if name.startswith(start):
            return query, passage
    return "", ""


def _load(model: str, cache_dir: Path) -> object:
    """One loaded model per (model, cache dir) and process."""
    key = (model, str(cache_dir))
    with _models_lock:
        if key not in _loaded:
            try:
                from fastembed import TextEmbedding

                cache_dir.mkdir(parents=True, exist_ok=True)
                log.info("loading local embedding model %s (first run downloads it)", model)
                encoder = TextEmbedding(model_name=model, cache_dir=str(cache_dir))
            except Exception as exc:  # unknown model name, download failure, broken cache
                raise EmbeddingError(
                    f"local embedding model {model} could not be loaded ({type(exc).__name__})"
                ) from exc
            _loaded[key] = encoder
        return _loaded[key]


class LocalEmbedder:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._run_lock = (
            threading.Lock()
        )  # one inference at a time: the ONNX session already uses every core

    @property
    def configured(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return self._s.embedding_model

    @property
    def models(self) -> list[str]:
        return [self._s.embedding_model]

    def available(self) -> list[str]:
        return self.models

    def mark_down(self, model: str, seconds: float = 0) -> None:
        """A local model is never skipped: a failure here is not a quota that recovers by waiting."""

    def warm(self) -> None:
        """Load the model in a background thread so the first upload or question does not wait for it."""

        def run() -> None:
            try:
                _load(self.model, self._s.model_cache_dir)
            except EmbeddingError as exc:
                log.warning("%s", exc)

        threading.Thread(target=run, name="embed-load", daemon=True).start()

    def embed_documents(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        _, passage = _prefixes(self._check(model))
        return self._embed([passage + t[:MAX_CHARS] for t in texts])

    def embed_query(self, text: str, model: str | None = None) -> list[float]:
        return self.embed_queries([text], model)[0]

    def embed_queries(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        query, _ = _prefixes(self._check(model))
        with self._lock:
            found = {t: self._query_cache[t] for t in texts if t in self._query_cache}
        missing = [t for t in dict.fromkeys(texts) if t not in found]
        if missing:
            fresh = self._embed([query + t[:MAX_CHARS] for t in missing])
            found.update(zip(missing, fresh, strict=True))
            with self._lock:
                for t, v in zip(missing, fresh, strict=True):
                    self._query_cache[t] = v
                while len(self._query_cache) > QUERY_CACHE_SIZE:
                    self._query_cache.popitem(last=False)
        return [found[t] for t in texts]

    def _check(self, model: str | None) -> str:
        if model and model != self.model:
            raise EmbeddingError(f"{model} is not the configured local embedding model")
        return self.model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        encoder = _load(self.model, self._s.model_cache_dir)
        out: list[list[float]] = []
        try:
            with self._run_lock:
                vectors = cast(
                    "list[Iterable[float]]",
                    list(encoder.embed(texts, batch_size=BATCH)),  # type: ignore[attr-defined]
                )
        except Exception as exc:
            raise EmbeddingError(f"local embedding failed ({type(exc).__name__})") from exc
        for vec in vectors:
            values = [float(v) for v in vec]
            if len(values) != EMBEDDING_DIM:
                raise EmbeddingError(
                    f"{self.model} returns {len(values)} dimensions, expected {EMBEDDING_DIM}; "
                    "choose a 768-dimension model for LOCAL_EMBEDDING_MODEL"
                )
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            out.append([v / norm for v in values])
        if len(texts) > BATCH:
            log.info("embedded %d passages locally", len(texts))
        return out


TextEmbedder = Embedder | LocalEmbedder


def create_embedder(settings: Settings) -> TextEmbedder:
    """The embedder EMBEDDING_PROVIDER names: the Gemini API (default) or the local model (warmed at once)."""
    if settings.embedding_provider == "local":
        embedder = LocalEmbedder(settings)
        embedder.warm()
        return embedder
    return Embedder(settings)
