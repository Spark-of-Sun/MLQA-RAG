from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from common.models import Action, Citation, ConfidentialityTier, TenantIndustry


class QueryRequest(BaseModel):
    question: str
    matter_or_patient_id: str
    session_id: str | None = None


class CitedAnswer(BaseModel):
    answer_text: str
    citations: list[Citation]
    validation_outcome: str


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    status: str
    matter_or_patient_id: str
    confidentiality_tier: ConfidentialityTier
    uploaded_at: datetime | None = None


class TenantCreateRequest(BaseModel):
    name: str
    industry: TenantIndustry


class RoleScopeUpdateRequest(BaseModel):
    tenant_id: str
    matter_or_patient_id: str | None = None
    action: Action

