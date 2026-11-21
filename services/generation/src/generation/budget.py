"""The hard per-request token budget (doc 11.4).

Count before sending, trim by relevance and never by truncation, and order what is kept so the
most relevant chunks sit at the start and the end of the prompt (not the middle). The count uses
a tokenizer and a safety margin, because the provider's own tokenizer differs; the live gate G6.1
compares against the provider's reported usage. Chunks are dropped WHOLE and every drop is
recorded with its reason, so audit can answer whether a relevant passage was excluded for budget.

Not implemented in the MVP: LLMLingua-style prompt compression (it needs a model; deferred).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_CONTEXT_BUDGET: Final = 12_000
DEFAULT_MAX_OUTPUT: Final = 1_500
SAFETY_MARGIN: Final = 1.25


class TokenCounter(Protocol):
    """Anything that counts tokens."""

    def count(self, text: str) -> int:
        """Token count of ``text``."""
        ...


@dataclass(frozen=True, slots=True)
class Candidate:
    """A retrieved chunk offered to the prompt, most relevant first."""

    alias: str
    text: str
    rank: int
    block_overhead: str = ""  # the surrounding <chunk ...> markup, counted with the text


@dataclass(slots=True)
class Fitted:
    """What fits, in prompt order, and what was dropped and why."""

    kept: list[Candidate]
    dropped: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    tokens: int = 0


def estimate(counter: TokenCounter, text: str) -> int:
    """A conservative token estimate: the counted tokens times the safety margin, rounded up."""
    return int(counter.count(text) * SAFETY_MARGIN) + 1


def reorder_for_attention(ranked: Sequence[Candidate]) -> list[Candidate]:
    """Most relevant first and last, least relevant in the middle (rank 1, 3, 5 ... 6, 4, 2)."""
    front, back = list(ranked[0::2]), list(ranked[1::2])
    return [*front, *reversed(back)]


def fit(
    counter: TokenCounter,
    fixed_text: str,
    ranked: Sequence[Candidate],
    *,
    budget: int = DEFAULT_CONTEXT_BUDGET,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> Fitted:
    """Keep the most relevant chunks that fit ``budget`` minus the fixed prompt and the output.

    Raises:
        ValueError: even the fixed text (system prompt and question) does not fit.
    """
    available = budget - max_output - estimate(counter, fixed_text)
    if available <= 0:
        msg = "the system prompt and question alone exceed the token budget"
        raise ValueError(msg)
    kept: list[Candidate] = []
    result = Fitted(kept)
    used = 0
    for cand in sorted(ranked, key=lambda c: c.rank):
        cost = estimate(counter, cand.block_overhead + cand.text)
        if used + cost > available:
            result.dropped.append(
                {"alias": cand.alias, "reason": "token_budget", "tokens": cost, "rank": cand.rank}
            )
            continue
        kept.append(cand)
        used += cost
    result.kept = reorder_for_attention(kept)
    result.tokens = used + estimate(counter, fixed_text)
    return result
