"""Tests for Sealed Audit Chaining.

Enforces Master System Design §5.5 and Gate G1.8.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from lmqa_audit import (
    GENESIS_HASH,
    AuditEntry,
    AuditEvent,
    canonical_json,
    create_sealed_entry,
    verify_audit_chain,
)


@pytest.mark.stage0
@pytest.mark.unit
def test_canonical_json_deterministic() -> None:
    data1 = {"b": 2, "a": 1, "nested": {"z": "last", "m": "middle"}}
    data2 = {"a": 1, "nested": {"m": "middle", "z": "last"}, "b": 2}
    assert canonical_json(data1) == canonical_json(data2)
    assert canonical_json(data1) == b'{"a":1,"b":2,"nested":{"m":"middle","z":"last"}}'


@pytest.mark.stage0
@pytest.mark.unit
def test_create_and_verify_valid_chain() -> None:
    org_id = uuid4()
    actor_id = uuid4()
    ws_id = uuid4()

    entries: list[AuditEntry] = []
    prev_hash = GENESIS_HASH

    for i in range(5):
        event = AuditEvent(
            org_id=org_id,
            workspace_id=ws_id,
            actor_id=actor_id,
            event_type=f"event_{i}",
            payload={"step": i, "details": "operation success"},
        )
        entry = create_sealed_entry(event, sequence_num=i, previous_hash=prev_hash)
        entries.append(entry)
        prev_hash = entry.entry_hash

    res = verify_audit_chain(entries)
    assert res.is_valid
    assert res.entries_verified == 5
    assert res.error is None


@pytest.mark.stage0
@pytest.mark.unit
def test_detect_tampered_payload() -> None:
    org_id = uuid4()
    actor_id = uuid4()

    entries: list[AuditEntry] = []
    prev_hash = GENESIS_HASH

    for i in range(3):
        event = AuditEvent(
            org_id=org_id,
            actor_id=actor_id,
            event_type="access",
            payload={"i": i},
        )
        entry = create_sealed_entry(event, sequence_num=i, previous_hash=prev_hash)
        entries.append(entry)
        prev_hash = entry.entry_hash

    # Tamper with middle entry payload
    tampered_entry = AuditEntry(
        sequence_num=entries[1].sequence_num,
        timestamp=entries[1].timestamp,
        org_id=entries[1].org_id,
        workspace_id=entries[1].workspace_id,
        actor_id=entries[1].actor_id,
        event_type=entries[1].event_type,
        payload={"i": 999},  # tampered
        previous_hash=entries[1].previous_hash,
        entry_hash=entries[1].entry_hash,
    )
    tampered_chain = [entries[0], tampered_entry, entries[2]]

    res = verify_audit_chain(tampered_chain)
    assert not res.is_valid
    assert res.tampered_sequence == 1
    assert "Tampered entry detected" in (res.error or "")


@pytest.mark.stage0
@pytest.mark.unit
def test_detect_sequence_gap() -> None:
    org_id = uuid4()
    actor_id = uuid4()

    event0 = AuditEvent(org_id=org_id, actor_id=actor_id, event_type="e0", payload={})
    entry0 = create_sealed_entry(event0, sequence_num=0, previous_hash=GENESIS_HASH)

    event2 = AuditEvent(org_id=org_id, actor_id=actor_id, event_type="e2", payload={})
    entry2 = create_sealed_entry(event2, sequence_num=2, previous_hash=entry0.entry_hash)

    res = verify_audit_chain([entry0, entry2])
    assert not res.is_valid
    assert "Sequence gap" in (res.error or "")
