from __future__ import annotations

from datetime import date

from common.models import ConfidentialityTier
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    tenant_id: str
    matter_or_patient_id: str
    confidentiality_tiers_allowed: list[ConfidentialityTier] = [ConfidentialityTier.STANDARD]
    top_k_dense: int = 40
    top_k_sparse: int = 40
    rerank_top_k: int = 8


class RankedChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    page: int
    section: str | None = None
    confidentiality_tier: ConfidentialityTier
    matter_or_patient_id: str
    effective_date: date | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    chunks: list[RankedChunkResponse]
    dropped_chunk_count: int
