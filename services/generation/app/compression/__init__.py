import os

from .base import Compressor
from .fake_backend import NoOpCompressor, WhitespaceCompressor


def get_compressor(backend: str | None = None) -> Compressor:
    backend = backend or os.environ.get("COMPRESSION_BACKEND", "whitespace")
    if backend == "llmlingua":
        from .llmlingua_backend import LLMLinguaCompressor

        return LLMLinguaCompressor()
    if backend == "whitespace":
        return WhitespaceCompressor()
    if backend == "none":
        return NoOpCompressor()
    raise ValueError(f"unknown COMPRESSION_BACKEND: {backend}")


__all__ = ["Compressor", "NoOpCompressor", "WhitespaceCompressor", "get_compressor"]
