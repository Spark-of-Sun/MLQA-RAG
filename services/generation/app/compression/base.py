from __future__ import annotations

from typing import Protocol


class Compressor(Protocol):
    def compress(self, text: str) -> str:
        """Shrinks token count while preserving specific facts/figures/
        dates a citation might need to point back to, per
        docs/architecture.md §4 step 3. Must never change the text's
        meaning or drop a figure/date/defined term."""
        ...
