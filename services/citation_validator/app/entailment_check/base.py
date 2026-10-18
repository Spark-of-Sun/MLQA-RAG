from __future__ import annotations

from typing import Protocol


class EntailmentChecker(Protocol):
    def score(self, claim_sentence: str, chunk_text: str) -> float:
        """Returns a 0.0-1.0 support score: how well chunk_text entails/
        supports claim_sentence. Catches the model attaching a real chunk
        ID to an unsupported claim, per docs/architecture.md §5 — this is
        the 'lightweight entailment check, not just ID presence' step."""
        ...
