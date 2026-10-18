from __future__ import annotations

from pydantic import BaseModel

from common.models import CitationCheck, ValidationOutcome


class ChunkForValidation(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    page: int
    section: str | None = None


class ValidateRequest(BaseModel):
    answer_text: str
    retrieved_chunks: list[ChunkForValidation]
    tenant_policy: str = "strip_unverified"  # "strip_unverified" | "regenerate"
    entailment_support_threshold: float = 0.55


class ResolvedCitationResponse(BaseModel):
    chunk_id: str
    document_id: str
    page: int
    section: str | None = None


class CitationFindingResponse(BaseModel):
    chunk_id_cited: str
    claim_sentence: str
    check: CitationCheck
    entailment_score: float | None = None


class ValidateResponse(BaseModel):
    validation_outcome: ValidationOutcome
    verified_answer_text: str
    resolved_citations: list[ResolvedCitationResponse]
    findings: list[CitationFindingResponse]
