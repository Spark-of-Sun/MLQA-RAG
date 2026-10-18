from __future__ import annotations

import re


class NoOpCompressor:
    """Passes text through unchanged — useful for tests that want to
    assert on exact chunk text without any transformation."""

    def compress(self, text: str) -> str:
        return text


class WhitespaceCompressor:
    """Cheap, dependency-free compression: collapses repeated whitespace
    and blank lines. This is a much weaker compressor than real LLMLingua
    (it doesn't drop low-information tokens), but it's deterministic,
    fast, and safe by construction — it can't accidentally drop a figure
    or date, which makes it a reasonable default before LLMLinguaCompressor
    is wired in and tuned per docs/architecture.md §4 step 3.
    """

    def compress(self, text: str) -> str:
        collapsed = re.sub(r"[ \t]+", " ", text)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        return collapsed.strip()

