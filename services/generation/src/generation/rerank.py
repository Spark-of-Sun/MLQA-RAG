"""Re-ranking with the answer models instead of a local cross-encoder (RERANK_MODEL=llm).

One request per question scores every candidate passage from 0 to 10; the score divided by 10 is the relevance that
RERANK_MIN_SCORE is compared with (the default 0.05 drops only passages scored 0, "unrelated"). The chain is
RERANK_LLM_MODELS, or by default the answer chain in reverse: the weakest, highest-quota model first, so re-ranking
leaves the strong models' small daily quota for answers. The request goes through the same client as answers: key
rotation, the local quota counter and the skip-when-busy logic all apply.

Ranking is not a safety boundary (the citation validator checks every sentence), so any failure here (no model
available, an unusable reply) raises RerankError and retrieval falls back to the fused order.
"""

from __future__ import annotations

import logging

from generation.llm_client import LLMClient, LLMError
from generation.prompts import RERANK_SCHEMA, load_prompts, rerank_user_prompt
from lmqa_models.rag import RerankError
from lmqa_models.settings import Settings, model_label

log = logging.getLogger(__name__)

MAX_PASSAGE_CHARS = 2000  # about 500 tokens: enough to judge relevance, and 40 candidates stay near 20k tokens
MAX_SCORE = 10


class LLMReranker:
    """Implements retrieval's PassageScorer protocol."""

    local = False

    def __init__(self, settings: Settings) -> None:
        self.client = LLMClient(settings.reranker_settings())

    @property
    def model(self) -> str:
        """The first model of the re-ranking chain (the one normally used)."""
        return self.client.model

    @property
    def models(self) -> list[str]:
        """The usable re-ranking chain, in the order it is tried."""
        return [model_label(p, m) for p, m in self.client.chain]

    def warm(self) -> None:
        """Nothing to load."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        clipped = [p if len(p) <= MAX_PASSAGE_CHARS else p[:MAX_PASSAGE_CHARS] + "…" for p in passages]
        try:
            out = self.client.generate_json(
                system=load_prompts().rerank_system,
                user=rerank_user_prompt(query, clipped),
                schema=RERANK_SCHEMA,
            )
        except LLMError as exc:
            raise RerankError(f"LLM re-ranking unavailable ({exc})") from exc
        scores: dict[int, float] = {}
        for item in out.data.get("scores") or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id", "")).strip().upper().removeprefix("P")
            try:
                n, value = int(pid), float(item.get("score", 0))
            except TypeError, ValueError:
                continue
            if 1 <= n <= len(passages):
                scores.setdefault(n, min(max(value, 0.0), MAX_SCORE) / MAX_SCORE)
        if len(scores) < len(passages):
            # A partial reply would silently drop the passages it left out; use the fused order instead.
            raise RerankError(f"LLM re-ranking scored {len(scores)} of {len(passages)} passages ({out.model})")
        log.debug("re-ranked %d passages with %s", len(passages), out.model)
        return [scores[i] for i in range(1, len(passages) + 1)]
