import os

from .base import EmbeddingBackend
from .fake_backend import FakeEmbeddingBackend


def get_embedding_backend(provider: str | None = None) -> EmbeddingBackend:
    provider = provider or os.environ.get("EMBEDDING_PROVIDER", "fake")
    if provider == "sentence-transformers":
        from .sentence_transformers_backend import SentenceTransformersBackend

        return SentenceTransformersBackend()
    if provider == "fake":
        return FakeEmbeddingBackend()
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {provider}")


__all__ = ["EmbeddingBackend", "FakeEmbeddingBackend", "get_embedding_backend"]

