"""Deployment settings (docs/deploy.md): EMBEDDING_PROVIDER=local selects the on-machine embedder with one model and
no fallbacks, the Gemini default is unchanged, and the local embedder applies each model's retrieval prefixes and
returns unit vectors of the schema's dimension."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from lmqa_models import envfile
from lmqa_models.settings import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    EMBEDDING_DIM,
    ConfigError,
    Settings,
    load_settings,
)
from lmqa_vectorstore import (
    Embedder,
    EmbeddingError,
    LocalEmbedder,
    create_embedder,
    local_embeddings,
)

pytestmark = [pytest.mark.contract, pytest.mark.stage0]


def _settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> Settings:
    path = tmp_path / ".env.deployed"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(envfile, "ENV_FILE", path)
    for key in ("EMBEDDING_PROVIDER", "LOCAL_EMBEDDING_MODEL", "GEMINI_EMBEDDING_MODEL"):
        monkeypatch.delenv(key, raising=False)
    return load_settings()


def test_gemini_stays_the_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    s = _settings(monkeypatch, tmp_path, "")
    assert s.embedding_provider == "gemini"
    assert s.embedding_models[0] == "gemini-embedding-001"
    assert isinstance(create_embedder(s), Embedder)


def test_local_provider_has_one_model_and_no_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    s = _settings(
        monkeypatch,
        tmp_path,
        "EMBEDDING_PROVIDER=local\nGEMINI_EMBEDDING_FALLBACK_MODELS=gemini-embedding-2\n",
    )
    assert s.embedding_provider == "local"
    assert s.embedding_models == [DEFAULT_LOCAL_EMBEDDING_MODEL]
    s = _settings(
        monkeypatch, tmp_path, "EMBEDDING_PROVIDER=LOCAL\nLOCAL_EMBEDDING_MODEL=nomic-ai/x\n"
    )
    assert s.embedding_models == ["nomic-ai/x"]


def test_unknown_provider_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="EMBEDDING_PROVIDER"):
        _settings(monkeypatch, tmp_path, "EMBEDDING_PROVIDER=openai\n")


class _FakeEncoder:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.seen: list[str] = []

    def embed(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        self.seen.extend(texts)
        return [[3.0, 4.0] + [0.0] * (self.dim - 2) for _ in texts]


def _local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, model: str, dim: int = EMBEDDING_DIM
) -> tuple[LocalEmbedder, _FakeEncoder]:
    s = _settings(
        monkeypatch, tmp_path, f"EMBEDDING_PROVIDER=local\nLOCAL_EMBEDDING_MODEL={model}\n"
    )
    fake = _FakeEncoder(dim)
    monkeypatch.setattr(local_embeddings, "_load", lambda _m, _d: fake)
    return LocalEmbedder(s), fake


def test_bge_prefixes_queries_only_and_vectors_are_unit_length(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    emb, fake = _local(monkeypatch, tmp_path, "BAAI/bge-base-en-v1.5")
    [doc] = emb.embed_documents(["Either party may terminate."])
    [q] = emb.embed_queries(["When can a party terminate?"])
    assert fake.seen[0] == "Either party may terminate."
    assert fake.seen[1].startswith("Represent this sentence for searching relevant passages: ")
    assert len(doc) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(v * v for v in q)), 1.0)
    emb.embed_queries(["When can a party terminate?"])  # cached: not embedded again
    assert len(fake.seen) == 2


def test_nomic_prefixes_both_sides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    emb, fake = _local(monkeypatch, tmp_path, "nomic-ai/nomic-embed-text-v1.5")
    emb.embed_documents(["a"])
    emb.embed_query("b")
    assert fake.seen == ["search_document: a", "search_query: b"]


def test_wrong_dimension_or_model_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    emb, _ = _local(monkeypatch, tmp_path, "BAAI/bge-small-en-v1.5", dim=384)
    with pytest.raises(EmbeddingError, match="768"):
        emb.embed_documents(["a"])
    with pytest.raises(EmbeddingError, match="not the configured"):
        emb.embed_query("a", model="gemini-embedding-001")
