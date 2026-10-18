from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ValidationOutcome(str, Enum):
    PASS = "pass"
    STRIPPED_UNVERIFIED = "stripped_unverified"
    REGENERATE_REQUIRED = "regenerate_required"


class CitationCheck(str, Enum):
    CHUNK_NOT_IN_RETRIEVED_SET = "chunk_not_in_retrieved_set"
    ENTAILMENT_BELOW_THRESHOLD = "entailment_below_threshold"
    OK = "ok"


class Citation(BaseModel):
    """A resolved, validated citation — what the frontend renders as [1], [2]."""

    chunk_id: str
    document_id: str
    page: int
    section: str | None = None


class CitationFinding(BaseModel):
    """One row of Citation Validator's per-claim audit trail.
    Matches docs/api-contracts/citation-validator.yaml#CitationFinding.
    """

    chunk_id_cited: str
    claim_sentence: str
    check: CitationCheck
    entailment_score: float | None = None
