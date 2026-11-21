"""Role-scoped audit views (blueprint 5.2): the Super Admin sees organization-level events (never workspace
content), an admin sees their workspace, a tenant sees their own history. Payloads carry hashes and counts,
not question or answer text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import lmqa_audit
from lmqa_db import Database
from lmqa_models.principal import Principal


class AuditService:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _scope(p: Principal) -> tuple[str, list[Any]]:
        m = p.membership
        assert m is not None
        if m.role == "super_admin":
            return "e.org_id = %s and e.workspace_id is null", [m.org_id]
        if m.role == "admin":
            return "e.org_id = %s and e.workspace_id = %s", [m.org_id, m.workspace_id]
        return "e.workspace_id = %s and e.actor_id = %s", [m.workspace_id, p.user_id]

    def events(self, p: Principal, limit: int = 100, before: int | None = None) -> list[dict[str, Any]]:
        where, args = self._scope(p)
        if before is not None:
            where += " and e.id < %s"
            args.append(before)
        with self._db.system() as conn:
            rows = conn.execute(
                "select e.id, e.created_at, e.action, e.target_type, e.target_id, e.payload, e.hash,"
                " u.email as actor_email, u.name as actor_name from audit_events e"
                f" left join users u on u.id = e.actor_id where {where} order by e.id desc limit %s",
                [*args, min(max(limit, 1), 500)],
            ).fetchall()
        out = []
        for r in rows:
            item = {
                k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, UUID) else v)
                for k, v in r.items()
            }
            out.append(item)
        return out

    def verify(self, p: Principal) -> dict[str, Any]:
        """Recompute the organization's whole chain; report only the count visible to this role."""
        m = p.membership
        assert m is not None
        where, args = self._scope(p)
        with self._db.system() as conn:
            status = lmqa_audit.verify_chain(conn, m.org_id)
            row = conn.execute(f"select count(*) as n from audit_events e where {where}", args).fetchone()
        assert row is not None
        return {"ok": status.ok, "events_in_scope": int(row["n"]), "first_bad_id": status.first_bad_id}
