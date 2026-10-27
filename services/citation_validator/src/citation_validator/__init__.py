"""Citation validator package providing deterministic verification."""

from __future__ import annotations

from citation_validator.engine import (
    CANONICAL_REFUSAL,
    SentenceValidator,
    extract_critical_tokens,
    segment_sentences,
)

__all__ = [
    "CANONICAL_REFUSAL",
    "SentenceValidator",
    "extract_critical_tokens",
    "segment_sentences",
]
