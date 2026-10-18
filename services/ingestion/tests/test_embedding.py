from __future__ import annotations

from app.embedding import FakeEmbeddingBackend, get_embedding_backend


def test_get_embedding_backend_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    backend = get_embedding_backend()
    assert isinstance(backend, FakeEmbeddingBackend)


def test_fake_embedding_is_deterministic():
    backend = FakeEmbeddingBackend(dimension=16)
    v1 = backend.embed(["hello"])[0]
    v2 = backend.embed(["hello"])[0]
    assert v1 == v2
    assert len(v1) == 16


def test_fake_embedding_differs_for_different_text():
    backend = FakeEmbeddingBackend(dimension=16)
    v1, v2 = backend.embed(["hello", "goodbye"])
    assert v1 != v2
