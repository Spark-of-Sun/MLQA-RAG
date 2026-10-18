import os

from .base import Reranker
from .fake_backend import FakeReranker


def get_reranker(model: str | None = None) -> Reranker:
    model = model or os.environ.get("RERANKER_MODEL", "fake")
    if model == "fake":
        return FakeReranker()
    from .cross_encoder_backend import CrossEncoderReranker

    return CrossEncoderReranker(model_name=model)


__all__ = ["Reranker", "FakeReranker", "get_reranker"]

