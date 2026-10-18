from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from common.models import ConfidentialityTier, TenantIndustry


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    status: str
    matter_or_patient_id: str
    confidentiality_tier: ConfidentialityTier
    industry: TenantIndustry | None = None
    uploaded_at: datetime | None = None

