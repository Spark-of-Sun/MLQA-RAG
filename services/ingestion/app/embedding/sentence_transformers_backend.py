from __future__ import annotations

import os


class SentenceTransformersBackend:
    """Real CPU-friendly checkpoint, per docs/architecture.md §6 ('No GPU
    dependency required locally'). Lazily imports sentence-transformers
    so this module can be imported without the '[real]' extra installed.
    """

    def __init__(self, model_name: str | None = None, device: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "SentenceTransformersBackend requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        self._model = SentenceTransformer(
            model_name or os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5"),
            device=device or os.environ.get("EMBEDDING_DEVICE", "cpu"),
        )
        self.dimension = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()
