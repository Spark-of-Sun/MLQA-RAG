import os

from .base import EntailmentChecker
from .fake_backend import WordOverlapEntailmentChecker


def get_entailment_checker(backend: str | None = None) -> EntailmentChecker:
    backend = backend or os.environ.get("ENTAILMENT_BACKEND", "fake")
    if backend == "cross-encoder":
        from .real_backend import CrossEncoderEntailmentChecker

        return CrossEncoderEntailmentChecker()
    if backend == "fake":
        return WordOverlapEntailmentChecker()
    raise ValueError(f"unknown ENTAILMENT_BACKEND: {backend}")


__all__ = ["EntailmentChecker", "WordOverlapEntailmentChecker", "get_entailment_checker"]
