"""The validator service: segment, check against the live ledger and chunks, sign each verdict.

A verdict is signed with a KMS-certified ephemeral key over ``(request_id, sentence sha256,
verdict, check results)`` and carries the sentence text. The Gateway releases a sentence only if it
holds a verdict, signed by the validator, for exactly that sentence and this request (doc 11.6).
Chunks are reloaded for every sentence, so a chunk changed or made unreadable mid-stream (a wall,
a suspension, a crypto-erase) fails V3 on the very next sentence.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Final

from citation_validator.checks import CHECK_ORDER, evaluate_sentence, sha256_hex
from citation_validator.segmenter import SEGMENTER_VERSION, StreamSegmenter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from citation_validator.checks import NliScorer
    from citation_validator.store import ValidatorStore
    from lmqa_auth import ContextSigner
    from lmqa_db import DbContext

VERDICT_PREFIX: Final = b"lmqa/verdict/v1|"


def signing_bytes(payload: dict[str, Any]) -> bytes:
    """The exact bytes that are signed: a fixed prefix plus canonical JSON of the payload."""
    return VERDICT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class SignedVerdict:
    """A verdict the Gateway can verify without trusting the network between the two services."""

    payload: dict[str, Any]
    certificate: str
    signature: str  # base64 of the ECDSA signature

    def to_json(self) -> dict[str, Any]:
        """Serializable form."""
        return asdict(self)


class ValidatorService:
    """Holds the store, the signer, the pinned scorer and the (calibrated) threshold."""

    def __init__(
        self, store: ValidatorStore, signer: ContextSigner, scorer: NliScorer, threshold: float
    ) -> None:
        """Bind the components. ``threshold`` comes from calibration, never from a guess."""
        self._store, self._signer, self._scorer, self._threshold = store, signer, scorer, threshold

    async def check(
        self, ctx: DbContext, request_id: UUID, sentence: str, index: int
    ) -> SignedVerdict:
        """Validate one sentence against the current ledger and chunks, and sign the verdict."""
        ledger = await self._store.ledger(ctx, request_id)
        chunks = await self._store.chunks(ctx, ledger)
        result = await asyncio.to_thread(
            evaluate_sentence, sentence, ledger, chunks, self._scorer, self._threshold
        )
        payload: dict[str, Any] = {
            "v": 1,
            "request_id": str(request_id),
            "index": index,
            "sentence": sentence,
            "sentence_sha256": sha256_hex(sentence),
            "passed": result.passed,
            "refusal": result.refusal,
            "failed_check": result.failed,
            "checks": {c: result.checks.get(c) for c in CHECK_ORDER if c in result.checks},
            "aliases": result.aliases,
            "citations": [asdict(c) for c in result.citations],
            "entailment": result.entailment,
            "threshold": self._threshold,
            "scorer": self._scorer.model_id,
            "segmenter": SEGMENTER_VERSION,
        }
        certificate, signature = await self._signer.sign_bytes(signing_bytes(payload))
        return SignedVerdict(payload, certificate, base64.b64encode(signature).decode())

    async def validate_answer(
        self, ctx: DbContext, request_id: UUID, answer: str
    ) -> list[SignedVerdict]:
        """Buffered mode: segment the whole answer and validate every sentence in order."""
        seg = StreamSegmenter()
        sentences = [*seg.feed(answer), *seg.finish()]
        return [await self.check(ctx, request_id, s, i) for i, s in enumerate(sentences)]

    async def validate_stream(
        self, ctx: DbContext, request_id: UUID, deltas: AsyncIterator[str]
    ) -> AsyncIterator[SignedVerdict]:
        """Streaming mode: yield a signed verdict as soon as each sentence is certainly complete."""
        seg, index = StreamSegmenter(), 0
        async for delta in deltas:
            for sentence in seg.feed(delta):
                yield await self.check(ctx, request_id, sentence, index)
                index += 1
        for sentence in seg.finish():
            yield await self.check(ctx, request_id, sentence, index)
            index += 1
