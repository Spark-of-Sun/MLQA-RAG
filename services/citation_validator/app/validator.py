from __future__ import annotations

import re

from common.models import CitationCheck, ValidationOutcome

from app.entailment_check.base import EntailmentChecker
from app.parser import parse_citations
from app.schemas.requests import (
    ChunkForValidation,
    CitationFindingResponse,
    ResolvedCitationResponse,
    ValidateResponse,
)

_TAG_PATTERN = re.compile(r"\[([^\[\]\s]+)\]")


def validate_answer(
    *,
    answer_text: str,
    retrieved_chunks: list[ChunkForValidation],
    tenant_policy: str,
    entailment_support_threshold: float,
    entailment_checker: EntailmentChecker,
) -> ValidateResponse:
    """The hard gate before any answer reaches the user, per
    docs/architecture.md §5: parses every [chunk_N] tag, confirms the
    chunk was actually in the retrieved set, and runs a lightweight
    entailment check between the cited sentence and the chunk text.
    """
    retrieved_by_id = {c.chunk_id: c for c in retrieved_chunks}
    parsed = parse_citations(answer_text)

    findings: list[CitationFindingResponse] = []
    resolved: dict[str, ResolvedCitationResponse] = {}
    tag_check: dict[str, CitationCheck] = {}
    any_failure = False

    for citation in parsed:
        chunk_id = citation.chunk_id
        chunk = retrieved_by_id.get(chunk_id)

        if chunk is None:
            # Catches the model citing a chunk ID that doesn't exist /
            # wasn't in the set it was actually given.
            findings.append(
                CitationFindingResponse(
                    chunk_id_cited=chunk_id,
                    claim_sentence=citation.sentence,
                    check=CitationCheck.CHUNK_NOT_IN_RETRIEVED_SET,
                    entailment_score=None,
                )
            )
            tag_check[chunk_id] = CitationCheck.CHUNK_NOT_IN_RETRIEVED_SET
            any_failure = True
            continue

        score = entailment_checker.score(citation.sentence, chunk.text)
        if score < entailment_support_threshold:
            # Catches the model attaching a real chunk ID to an
            # unsupported claim.
            findings.append(
                CitationFindingResponse(
                    chunk_id_cited=chunk_id,
                    claim_sentence=citation.sentence,
                    check=CitationCheck.ENTAILMENT_BELOW_THRESHOLD,
                    entailment_score=score,
                )
            )
            tag_check[chunk_id] = CitationCheck.ENTAILMENT_BELOW_THRESHOLD
            any_failure = True
        else:
            findings.append(
                CitationFindingResponse(
                    chunk_id_cited=chunk_id,
                    claim_sentence=citation.sentence,
                    check=CitationCheck.OK,
                    entailment_score=score,
                )
            )
            tag_check.setdefault(chunk_id, CitationCheck.OK)
            resolved.setdefault(
                chunk_id,
                ResolvedCitationResponse(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    page=chunk.page,
                    section=chunk.section,
                ),
            )

    if not any_failure:
        outcome = ValidationOutcome.PASS
    elif tenant_policy == "regenerate":
        outcome = ValidationOutcome.REGENERATE_REQUIRED
    else:
        outcome = ValidationOutcome.STRIPPED_UNVERIFIED

    verified_answer_text = _rewrite_citations(answer_text, tag_check)

    return ValidateResponse(
        validation_outcome=outcome,
        verified_answer_text=verified_answer_text,
        resolved_citations=list(resolved.values()),
        findings=findings,
    )


def _rewrite_citations(answer_text: str, tag_check: dict[str, CitationCheck]) -> str:
    """Replaces raw [chunk_id] tags with sequential [1], [2]... for
    citations that passed (numbered in order of first appearance in the
    text), and with [unverified] for any that failed — per
    docs/architecture.md §5's 'stripped with a visible unverified flag'.
    A tag_check miss (a bracketed token that was never parsed as a
    citation, which shouldn't normally happen) is left untouched.
    """
    numbering: dict[str, int] = {}

    def _replace(match: re.Match) -> str:
        chunk_id = match.group(1)
        check = tag_check.get(chunk_id)
        if check == CitationCheck.OK:
            if chunk_id not in numbering:
                numbering[chunk_id] = len(numbering) + 1
            return f"[{numbering[chunk_id]}]"
        if check in (CitationCheck.CHUNK_NOT_IN_RETRIEVED_SET, CitationCheck.ENTAILMENT_BELOW_THRESHOLD):
            return "[unverified]"
        return match.group(0)

    return _TAG_PATTERN.sub(_replace, answer_text)
