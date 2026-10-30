"""Token counting with a Hugging Face fast tokenizer (a tokenizer is not a model run).

Shared by ingestion (chunk bounds) and generation (the hard per-request budget), so neither service
imports the other. The ``tokenizers`` package loads lazily, on first construction.
"""

from __future__ import annotations


class HfTokenizer:
    """The embedding model's own tokenizer: counts tokens without running any model."""

    def __init__(self, name: str = "BAAI/bge-small-en-v1.5") -> None:
        """Download (once) and load the tokenizer."""
        from tokenizers import Tokenizer  # noqa: PLC0415

        self._tok = Tokenizer.from_pretrained(name)

    def count(self, text: str) -> int:
        """Number of tokens, special tokens excluded."""
        return len(self._tok.encode(text, add_special_tokens=False).ids)
