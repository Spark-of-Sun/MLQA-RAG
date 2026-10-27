"""Audit domain models and verification structures.

Master System Design §5.5 & Gate G1.8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class AuditEvent:
    """Incoming audit event before sealing."""

    org_id: UUID
    actor_id: UUID
    event_type: str
    payload: dict[str, Any]
    workspace_id: UUID | None = None


@dataclass(frozen=True)
class AuditEntry:
    """A sealed, hash-chained audit ledger entry."""

    sequence_num: int
    timestamp: str
    org_id: UUID
    actor_id: UUID
    event_type: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str
    workspace_id: UUID | None = None


@dataclass(frozen=True)
class AuditVerificationResult:
    """Result of audit chain cryptographic verification."""

    is_valid: bool
    entries_verified: int
    error: str | None = None
    tampered_sequence: int | None = None
