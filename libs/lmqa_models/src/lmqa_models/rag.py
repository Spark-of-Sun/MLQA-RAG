"""Types passed between retrieval, generation, the citation validator and the gateway."""

from __future__ import annotations

from dataclasses import dataclass

# The one refusal sentence (blueprint 11.5). Shared by generation (prompt) and the validator (V7).
CANONICAL_REFUSAL = "The provided documents do not address this."


class RerankError(RuntimeError):
    """A re-ranker (local cross-encoder or the LLM chain) could not score passages; retrieval uses the fused order."""


@dataclass(frozen=True)
class Source:
    """A retrieved chunk. `alias` (S1, S2, ...) is request-local; the model never sees chunk IDs."""

    chunk_id: str
    document_id: str
    document_title: str
    section: str | None
    page_start: int | None
    page_end: int | None
    text: str
    sha256: str
    token_count: int
    score: float
    alias: str = ""

    def pages(self) -> str:
        if self.page_start is None:
            return ""
        if self.page_end and self.page_end != self.page_start:
            return f"{self.page_start}-{self.page_end}"
        return str(self.page_start)


@dataclass(frozen=True)
class Dropped:
    chunk_id: str
    reason: str  # not_visible | below_threshold | duplicate | below_top_k | token_budget
    score: float
