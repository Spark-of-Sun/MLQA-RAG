"""Audit client. Events go through the database function `audit_append` only, which chains each event to
the previous one of the same organization by SHA-256; UPDATE, DELETE and TRUNCATE are rejected by triggers.
Append in the same transaction as the action, so the event commits with it or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from lmqa_db import Scope


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    checked: int
    first_bad_id: int | None


def append(
    conn: psycopg.Connection[Any] | Scope,
    *,
    org_id: Any,
    action: str,
    workspace_id: Any = None,
    actor_id: Any = None,
    target_type: str | None = None,
    target_id: Any = None,
    payload: dict[str, Any] | None = None,
) -> int:
    row = conn.execute(
        "select audit_append(%s, %s, %s, %s, %s, %s, %s) as id",
        [
            str(org_id),
            str(workspace_id) if workspace_id else None,
            str(actor_id) if actor_id else None,
            action,
            target_type,
            str(target_id) if target_id else None,
            Jsonb(payload or {}),
        ],
    ).fetchone()
    assert row is not None
    return int(row["id"])


def verify_chain(conn: psycopg.Connection[Any], org_id: Any) -> ChainStatus:
    row = conn.execute("select ok, checked, first_bad_id from audit_verify(%s)", [str(org_id)]).fetchone()
    assert row is not None
    return ChainStatus(bool(row["ok"]), int(row["checked"]), row["first_bad_id"])
