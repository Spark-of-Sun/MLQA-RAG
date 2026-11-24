"""Sealed audit payloads (blueprint 13.2, D31, KD-10; R-60.2, R-60.3). `lmqa_audit.append(..., content=...)` seals
the content with HPKE to the active public key of the event's chain (the workspace, or the organization control chain)
for the current UTC month, and `audit_append` stores the ciphertext in `audit_payloads` and its SHA-256 in the chain.
Only the `audit` service can open payloads (`lmqa_keys.KeyRing.audit_private_key`).

Writers read public keys through the definer function `audit_public_key`, never the `audit_keys` table. A missing key
fails closed with `AuditUnavailableError`: the action and its event roll back together. Public keys are cached per
process for an hour; `audit_append` still refuses a key that is not active for the chain and month.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from lmqa_security.sealing import seal

_KEYS: dict[tuple[str, str | None, date], tuple[float, PublicKey]] = {}
_TTL = 3600.0


class AuditUnavailableError(RuntimeError):
    """No active audit key for the chain and month, or the database refused the write: fail closed (503)."""


@dataclass(frozen=True)
class PublicKey:
    key_id: int  # audit_keys.id, stored with the payload as its audit key reference
    month: date
    public_key: bytes  # raw X25519, 32 bytes


@dataclass(frozen=True)
class SealedPayload:
    key_id: int
    ciphertext: bytes


def current_month(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return date(now.year, now.month, 1)


def public_key(conn: Any, org_id: Any, workspace_id: Any, month: date) -> PublicKey:
    ws = str(workspace_id) if workspace_id else None
    cache_key = (str(org_id), ws, month)
    hit = _KEYS.get(cache_key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    row: dict[str, Any] | None = conn.execute(
        "select key_id, month, public_key from audit_public_key(%s, %s, %s)",
        [str(org_id), ws, month],
    ).fetchone()
    if not row:
        raise AuditUnavailableError(
            f"no active audit key for organization {org_id}, {ws or 'control chain'}, month {month}"
        )
    key = PublicKey(int(row["key_id"]), row["month"], bytes(row["public_key"]))
    _KEYS[cache_key] = (time.monotonic() + _TTL, key)
    return key


def seal_content(
    conn: Any, *, org_id: Any, workspace_id: Any, action: str, content: Mapping[str, Any]
) -> SealedPayload:
    key = public_key(conn, org_id, workspace_id, current_month())
    ciphertext = seal(
        content,
        key.public_key,
        org_id=org_id,
        workspace_id=workspace_id,
        month=key.month,
        action=action,
    )
    return SealedPayload(key.key_id, ciphertext)
