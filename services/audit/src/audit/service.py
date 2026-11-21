"""Role-scoped audit views (blueprint 5.2, 13).

Scope by role:
  super_admin  organization-level events (no workspace content)
  admin        every event in their workspace
  tenant       their own actions, decisions about their membership, and documents shared with them or with the
               whole workspace
Payloads carry hashes and counts, never question or answer text. A document title is shown only to people who can
see the document (its owner, everyone for workspace documents, the named recipients of a share). The same rule
applies to search, so the filter cannot be used to probe the names of private documents.

Categories group actions per role; filters (category, action, person, dates, free text) are applied in SQL so
pagination stays correct.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import lmqa_audit
from lmqa_db import Database
from lmqa_models.errors import BadRequest
from lmqa_models.principal import Principal

CATEGORIES: dict[str, dict[str, list[str]]] = {
    "super_admin": {"admins": ["admin."], "codes": ["code."], "organization": ["org.", "profile."]},
    "admin": {
        "members": ["tenant.", "profile."],
        "library": ["document."],
        "chats": ["query.", "conversation."],
        "codes": ["code."],
    },
    "tenant": {"library": ["document."], "chats": ["query.", "conversation."]},
}
# Payload keys that are safe to show for a document the viewer cannot see.
OPAQUE_DOC_KEYS = {"type", "bytes", "chunks", "pages", "structure", "reason", "visibility"}


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        return (
            "e.workspace_id = %s and (e.actor_id = %s::uuid"
            " or (e.target_type = 'membership' and e.target_id = %s)"
            " or (e.target_type = 'user' and e.target_id = %s)"
            " or (e.action like 'document.%%' and (e.payload->>'visibility' = 'workspace'"
            "     or jsonb_exists(coalesce(e.payload->'shared_with', '[]'::jsonb), %s))))",
            [m.workspace_id, p.user_id, m.id, p.user_id, p.user_id],
        )

    @staticmethod
    def _title_visible(p: Principal) -> tuple[str, list[Any]]:
        return (
            "(e.actor_id = %s::uuid or e.payload->>'visibility' = 'workspace'"
            " or jsonb_exists(coalesce(e.payload->'shared_with', '[]'::jsonb), %s))",
            [p.user_id, p.user_id],
        )

    def events(
        self,
        p: Principal,
        limit: int = 100,
        before: int | None = None,
        *,
        category: str | None = None,
        action: str | None = None,
        actor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        m = p.membership
        assert m is not None
        where, args = self._scope(p)
        visible, visible_args = self._title_visible(p)
        if category and category != "all":
            prefixes = CATEGORIES[m.role].get(category)
            if prefixes is None:
                raise BadRequest(f"Unknown audit category {category!r}.")
            where += " and e.action like any(%s)"
            args.append([f"{x}%" for x in prefixes])
        if action:
            where += " and e.action = %s"
            args.append(action[:80])
        if actor == "me":
            where += " and e.actor_id = %s::uuid"
            args.append(p.user_id)
        elif actor == "others":
            where += " and e.actor_id is distinct from %s::uuid"
            args.append(p.user_id)
        elif actor:
            try:
                args.append(str(uuid.UUID(actor)))
            except ValueError as exc:
                raise BadRequest("Unknown person filter.") from exc
            where += " and e.actor_id = %s::uuid"
        if since is not None:
            where += " and e.created_at >= %s"
            args.append(since)
        if until is not None:
            where += " and e.created_at < %s"
            args.append(until)
        if q and q.strip():
            pattern = f"%{_like_escape(q.strip()[:100])}%"
            where += (
                " and (e.action ilike %s or u.name ilike %s or u.email ilike %s or e.target_id ilike %s"
                f" or (e.payload->>'title' ilike %s and {visible})"
                " or e.payload->>'outcome' ilike %s or e.payload->>'reason' ilike %s)"
            )
            args += [pattern] * 5 + visible_args + [pattern] * 2
        if before is not None:
            where += " and e.id < %s"
            args.append(before)
        with self._db.system() as conn:
            rows = conn.execute(
                "select e.id, e.created_at, e.action, e.target_type, e.target_id, e.payload, e.hash, e.prev_hash,"
                f" e.actor_id, u.email as actor_email, u.name as actor_name, {visible} as title_visible"
                " from audit_events e left join users u on u.id = e.actor_id"
                f" where {where} order by e.id desc limit %s",
                [*visible_args, *args, min(max(limit, 1), 500)],
            ).fetchall()
            out = [self._redact(p, r) for r in rows]
            people = {u for e in out for u in e["payload"].get("shared_with", [])}
            names: dict[str, str] = {}
            if people:
                for r in conn.execute(
                    "select id, coalesce(name, email) as label from users where id = any(%s::uuid[])", [list(people)]
                ).fetchall():
                    names[str(r["id"])] = r["label"] or "User"
        for e in out:
            if e["payload"].get("shared_with"):
                e["shared_with_names"] = [names.get(u, "User") for u in e["payload"]["shared_with"]]
        return out

    @staticmethod
    def _redact(p: Principal, r: dict[str, Any]) -> dict[str, Any]:
        payload = dict(r["payload"] or {})
        mine = r["actor_id"] is not None and str(r["actor_id"]) == p.user_id
        if r["action"].startswith("document.") and not r["title_visible"]:
            payload = {k: v for k, v in payload.items() if k in OPAQUE_DOC_KEYS}
        if not mine and isinstance(payload.get("shared_with"), list):
            # Recipients other than the viewer are the owner's business.
            payload["shared_with"] = [u for u in payload["shared_with"] if u == p.user_id]
        return {
            "id": r["id"],
            "created_at": r["created_at"].isoformat(),
            "action": r["action"],
            "target_type": r["target_type"],
            "target_id": r["target_id"],
            "payload": payload,
            "hash": r["hash"],
            "prev_hash": r["prev_hash"],
            "actor_email": r["actor_email"],
            "actor_name": r["actor_name"],
            "actor_is_me": mine,
        }

    def verify(self, p: Principal) -> dict[str, Any]:
        """Recompute the organization's whole chain; report only the count visible to this role."""
        m = p.membership
        assert m is not None
        where, args = self._scope(p)
        with self._db.system() as conn:
            status = lmqa_audit.verify_chain(conn, m.org_id)
            row = conn.execute(f"select count(*) as n from audit_events e where {where}", args).fetchone()
        assert row is not None
        return {
            "ok": status.ok,
            "checked": status.checked,
            "events_in_scope": int(row["n"]),
            # Event IDs outside a member's own view are not theirs to see.
            "first_bad_id": status.first_bad_id if m.role != "tenant" else None,
        }
