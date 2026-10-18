from __future__ import annotations

from dataclasses import replace


class CrossEncoderReranker:
    """Real backend — a bge-reranker (or Cohere Rerank) cross-encoder on
    the top-k dense+sparse candidates, per docs/architecture.md §4. Lazily
    imports sentence-transformers so this module can be imported without
    the '[real]' extra installed.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str | None = None):
        import os

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "CrossEncoderReranker requires the 'real' extra: pip install -e '.[real]'"
            ) from exc

        self._model = CrossEncoder(
            model_name, device=device or os.environ.get("RERANKER_DEVICE", "cpu")
        )

    def rerank(self, query, candidates, top_k):
        if not candidates:
            return []
        pairs = [(query, c.chunk.text) for c in candidates]
        scores = self._model.predict(pairs)
        scored = [replace(c, rerank_score=float(s)) for c, s in zip(candidates, scores)]
        scored.sort(key=lambda c: c.rerank_score, reverse=True)
        return scored[:top_k]
