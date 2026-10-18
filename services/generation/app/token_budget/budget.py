from __future__ import annotations

from dataclasses import dataclass

from app.schemas.requests import InputChunk
from app.token_budget.counter import TokenCounter

_PROMPT_OVERHEAD_TOKENS = 300  # system instructions + few-shot examples + question, approx


@dataclass
class TrimResult:
    kept: list[InputChunk]
    dropped_chunk_ids: list[str]
    prompt_tokens_estimate: int


def trim_chunks_by_budget(
    chunks: list[InputChunk],
    max_prompt_tokens: int,
    counter: TokenCounter,
    overhead_tokens: int = _PROMPT_OVERHEAD_TOKENS,
) -> TrimResult:
    """Trim by relevance, not truncation, per docs/architecture.md §4 step 2:
    chunks below budget are dropped ENTIRELY, never cut off mid-document —
    preserves the facts/dates a citation might need to point back to.
    Chunks are assumed already in rank order (most relevant first), as
    Retrieval returns them (docs/api-contracts/retrieval.yaml).
    """
    budget_remaining = max_prompt_tokens - overhead_tokens
    kept: list[InputChunk] = []
    dropped: list[str] = []
    running_total = overhead_tokens

    for chunk in chunks:
        chunk_tokens = counter.count(chunk.text)
        if chunk_tokens <= budget_remaining:
            kept.append(chunk)
            budget_remaining -= chunk_tokens
            running_total += chunk_tokens
        else:
            dropped.append(chunk.chunk_id)

    return TrimResult(kept=kept, dropped_chunk_ids=dropped, prompt_tokens_estimate=running_total)
