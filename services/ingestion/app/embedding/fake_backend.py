from __future__ import annotations

import hashlib


class FakeEmbeddingBackend:
    """Deterministic, zero-dependency embedding stand-in for local unit
    tests and offline dev: the same text always hashes to the same
    vector, so tests are reproducible without downloading a real model.
    Never used in the Docker image — see SentenceTransformersBackend for
    the real CPU-friendly checkpoint.
    """

    def __init__(self, dimension: int = 32):
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = (digest * ((self.dimension // len(digest)) + 1))[: self.dimension]
            vectors.append([b / 255.0 for b in raw])
        return vectors
