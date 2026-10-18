from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ConfidentialityTier(str, Enum):
    """Privilege/PHI tagging lives on the chunk from day one — see
    docs/architecture.md §7 (Security, compliance & governance)."""

    STANDARD = "standard"
    PRIVILEGED = "privileged"
    PHI = "phi"


class Chunk(BaseModel):
    """A single structure-aware chunk (clause/section for legal,
    note/encounter/section for medical). This is the unit a citation
    points to — preserve page/section exactly as ingested, never
    re-derive it downstream.
    """

    chunk_id: str
    document_id: str
    tenant_id: str
    matter_or_patient_id: str

    text: str
    page: int
    section: str | None = None

    confidentiality_tier: ConfidentialityTier = ConfidentialityTier.STANDARD
    effective_date: date | None = None

    # Populated by Retrieval; absent on chunks fresh out of Ingestion.
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_prompt_tag(self) -> str:
        """Matches docs/architecture.md §5 inline injection format exactly —
        the Citation Validator's parser depends on this format."""
        section_attr = f' section="{self.section}"' if self.section else ""
        return f'<chunk id="{self.chunk_id}" doc="{self.document_id}" page="{self.page}"{section_attr}>'
