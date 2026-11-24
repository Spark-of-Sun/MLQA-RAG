"""Audit client (blueprint 13, KD-10). Events go through the database function `audit_append` only. It appends to
the hash chain of the event's workspace, or of the organization control chain when there is no workspace, under a
per-chain transaction-level lock, so concurrent writers cannot fork a chain. UPDATE, DELETE and TRUNCATE are rejected
by triggers. Append in the same transaction as the action, so the event commits with it or not at all.

An event carries metadata (`payload`, checked by `AuditMeta`: no free text, R-60.5) and optionally content
(`content`: question text, chunk references, answer, verdicts...), which is sealed here with HPKE to the chain's
workspace-month public key before it reaches the database (R-60.2). The chain covers the ciphertext's SHA-256 (R-60.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lmqa_audit.meta import AuditMeta, FreeTextError, check_token
from lmqa_audit.sealed import AuditUnavailableError, seal_content
from lmqa_db import Scope

__all__ = [
    "SEVERITIES",
    "AuditMeta",
    "AuditUnavailableError",
    "ChainStatus",
    "FreeTextError",
    "append",
    "verify_chain",
    "verify_chain_id",
]

SEVERITIES = ("info", "notice", "warning", "break_glass", "critical")


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    checked: int
    first_bad_id: int | None


def _opt(value: Any) -> str | None:
    return str(value) if value else None


def append(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
    conn: psycopg.Connection[Any] | Scope,
    *,
    org_id: Any,
    action: str,
    workspace_id: Any = None,
    actor_id: Any = None,
    target_type: str | None = None,
    target_id: Any = None,
    payload: Mapping[str, Any] | None = None,
    content: Mapping[str, Any] | None = None,
    severity: str = "info",
    request_id: Any = None,
) -> int:
    """`payload` is event metadata, not content: it goes through `AuditMeta`, which rejects free text (R-60.5).
    `content` is sealed to the workspace-month audit key; without an active key this raises AuditUnavailableError."""
    meta = AuditMeta.of(payload)
    check_token(action, "audit action")
    if target_type is not None:
        check_token(target_type, "audit target_type")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    sealed = (
        seal_content(conn, org_id=org_id, workspace_id=workspace_id, action=action, content=content)
        if content is not None
        else None
    )
    row = conn.execute(
        "select audit_append(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) as id",
        [
            str(org_id),
            _opt(workspace_id),
            _opt(actor_id),
            action,
            target_type,
            _opt(target_id),
            Jsonb(meta.as_dict()),
            severity,
            _opt(request_id),
            sealed.ciphertext if sealed else None,
            sealed.key_id if sealed else None,
        ],
    ).fetchone()
    if row is None:
        raise AuditUnavailableError("audit_append returned nothing")
    return int(row["id"])


def _status(row: Any) -> ChainStatus:
    assert row is not None
    return ChainStatus(bool(row["ok"]), int(row["checked"]), row["first_bad_id"])


def verify_chain(conn: psycopg.Connection[Any] | Scope, org_id: Any) -> ChainStatus:
    """Every chain of the organization: its workspaces and its control chain."""
    return _status(
        conn.execute(
            "select ok, checked, first_bad_id from audit_verify(%s)", [str(org_id)]
        ).fetchone()
    )


def verify_chain_id(conn: psycopg.Connection[Any] | Scope, chain_id: Any) -> ChainStatus:
    return _status(
        conn.execute(
            "select ok, checked, first_bad_id from audit_verify_chain(%s)", [str(chain_id)]
        ).fetchone()
    )
