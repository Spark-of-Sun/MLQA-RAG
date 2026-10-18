from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .citation import ValidationOutcome


class AuditEvent(BaseModel):
    """Written by every service, on every request, to the append-only
    audit log (Postgres, insert-only grants locally; WORM storage in
    production). Never mutated after creation — see docs/architecture.md §6.
    """

    event_id: str
    tenant_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    user_id: str
    session_id: str
    matter_or_patient_id: str

    question: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    dropped_chunk_ids: list[str] = Field(default_factory=list)

    answer_text: str | None = None
    validation_outcome: ValidationOutcome | None = None

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

