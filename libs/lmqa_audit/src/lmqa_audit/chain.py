"""Sealed cryptographic audit chaining engine.

Master System Design §5.5 & Gate G1.8:
Enforces immutable, sequentially numbered, SHA-256 hash-chained audit logging
with deterministic RFC 8785 canonical JSON serialization.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from lmqa_audit.models import AuditEntry, AuditVerificationResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lmqa_audit.models import AuditEvent

GENESIS_HASH: str = "0" * 64


def canonical_json(data: dict[str, Any]) -> bytes:
    """Serialize data into deterministic canonical JSON (RFC 8785).

    Args:
        data: Arbitrary dictionary.

    Returns:
        UTF-8 encoded canonical JSON byte sequence.
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def compute_entry_hash(record: dict[str, Any]) -> str:
    """Compute SHA-256 hash over canonical audit record dictionary.

    Args:
        record: Dictionary containing audit record fields.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    canonical_bytes = canonical_json(record)
    return hashlib.sha256(canonical_bytes).hexdigest()


def make_audit_record(
    event: AuditEvent,
    sequence_num: int,
    previous_hash: str,
    timestamp: str,
) -> dict[str, Any]:
    """Create normalized dictionary representation from an unsealed AuditEvent."""
    return {
        "actor_id": str(event.actor_id),
        "event_type": event.event_type,
        "org_id": str(event.org_id),
        "payload": event.payload,
        "previous_hash": previous_hash,
        "sequence_num": sequence_num,
        "timestamp": timestamp,
        "workspace_id": str(event.workspace_id) if event.workspace_id else None,
    }


def make_entry_record(entry: AuditEntry) -> dict[str, Any]:
    """Create normalized dictionary representation from an existing AuditEntry."""
    return {
        "actor_id": str(entry.actor_id),
        "event_type": entry.event_type,
        "org_id": str(entry.org_id),
        "payload": entry.payload,
        "previous_hash": entry.previous_hash,
        "sequence_num": entry.sequence_num,
        "timestamp": entry.timestamp,
        "workspace_id": str(entry.workspace_id) if entry.workspace_id else None,
    }


def create_sealed_entry(
    event: AuditEvent,
    sequence_num: int,
    previous_hash: str,
    timestamp: str | None = None,
) -> AuditEntry:
    """Create a sealed, hash-chained AuditEntry from an AuditEvent.

    Args:
        event: Unsealed audit event.
        sequence_num: Monotonic sequence number for this entry.
        previous_hash: Hash of the predecessor entry.
        timestamp: Optional explicit timestamp string, or current UTC ISO-8601.

    Returns:
        Sealed AuditEntry.
    """
    ts = timestamp or datetime.now(UTC).isoformat()
    record = make_audit_record(
        event=event,
        sequence_num=sequence_num,
        previous_hash=previous_hash,
        timestamp=ts,
    )
    entry_hash = compute_entry_hash(record)
    return AuditEntry(
        sequence_num=sequence_num,
        timestamp=ts,
        org_id=event.org_id,
        workspace_id=event.workspace_id,
        actor_id=event.actor_id,
        event_type=event.event_type,
        payload=event.payload,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )


def verify_audit_chain(entries: Sequence[AuditEntry]) -> AuditVerificationResult:
    """Verify integrity and hash linkage of an audit entry sequence.

    Checks:
    1. Sequence numbers start at 0 and increase strictly by 1.
    2. First entry previous_hash is GENESIS_HASH.
    3. Every subsequent entry has previous_hash == predecessor's entry_hash.
    4. Each entry's entry_hash matches the recomputed SHA-256 of its content.

    Args:
        entries: Ordered list of AuditEntry records.

    Returns:
        AuditVerificationResult with validation outcome.
    """
    if not entries:
        return AuditVerificationResult(is_valid=True, entries_verified=0)

    expected_prev = GENESIS_HASH

    for i, entry in enumerate(entries):
        if entry.sequence_num != i:
            msg = f"Sequence gap at index {i}: expected sequence_num {i}, got {entry.sequence_num}"
            return AuditVerificationResult(
                is_valid=False,
                entries_verified=i,
                error=msg,
                tampered_sequence=entry.sequence_num,
            )

        if entry.previous_hash != expected_prev:
            msg = (
                f"Broken hash link at sequence {entry.sequence_num}: "
                f"expected previous_hash '{expected_prev}', got '{entry.previous_hash}'"
            )
            return AuditVerificationResult(
                is_valid=False,
                entries_verified=i,
                error=msg,
                tampered_sequence=entry.sequence_num,
            )

        record = make_entry_record(entry)
        recomputed = compute_entry_hash(record)

        if entry.entry_hash != recomputed:
            msg = f"Tampered entry detected at sequence {entry.sequence_num}: content hash mismatch"
            return AuditVerificationResult(
                is_valid=False,
                entries_verified=i,
                error=msg,
                tampered_sequence=entry.sequence_num,
            )

        expected_prev = entry.entry_hash

    return AuditVerificationResult(is_valid=True, entries_verified=len(entries))
