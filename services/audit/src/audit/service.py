"""Role-scoped audit views (blueprint 5.2, 13).

Scope by role:
  super_admin  organization-level events (no workspace content)
  admin        every event in their workspace
  tenant       their own actions, decisions about their membership, and documents shared with them or with the
               whole workspace (frozen MVP-only features `named_shares` and `workspace_visibility`, DEV-21: while
               their flags are off a tenant sees only their own document events)
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
from lmqa_keys import FieldCipher, field_cipher_from_settings
from lmqa_models.contracts import feature_enabled
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
    def __init__(self, db: Database, keys: FieldCipher | None = None) -> None:
        self._db = db
        self._keys = keys or field_cipher_from_settings()

    @staticmethod
    def _shared(p: Principal) -> tuple[str, list[Any]]:
        """Document events the viewer may see without owning the document: workspace documents and named shares.
        Both are frozen MVP-only features (DEV-21); with their flags off neither adds anything to a tenant's view."""
        terms, args = [], []
        if feature_enabled("workspace_visibility"):
            terms.append("e.meta->>'visibility' = 'workspace'")
        if feature_enabled("named_shares"):
            terms.append("jsonb_exists(coalesce(e.meta->'shared_with', '[]'::jsonb), %s)")
            args.append(p.user_id)
        return (f"({' or '.join(terms)})" if terms else "false"), args

    @classmethod
    def _scope(cls, p: Principal) -> tuple[str, list[Any]]:
        m = p.membership
        assert m is not None
        if m.role == "super_admin":
            return "e.org_id = %s and e.workspace_id is null", [m.org_id]
        if m.role == "admin":
            return "e.org_id = %s and e.workspace_id = %s", [m.org_id, m.workspace_id]
        shared, shared_args = cls._shared(p)
        return (
            "e.workspace_id = %s and (e.actor_id = %s::uuid"
            " or (e.target_type = 'membership' and e.target_id = %s)"
            " or (e.target_type = 'user' and e.target_id = %s)"
            f" or (e.action like 'document.%%' and {shared}))",
            [m.workspace_id, p.user_id, m.id, p.user_id, *shared_args],
        )

    @classmethod
    def _title_visible(cls, p: Principal) -> tuple[str, list[Any]]:
        shared, shared_args = cls._shared(p)
        return f"(e.actor_id = %s::uuid or {shared})", [p.user_id, *shared_args]

    def events(  # noqa: C901, PLR0912, PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
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
        with self._db.as_service("audit", p) as conn:
            if q and q.strip():
                # Names and emails are encrypted (R-51.3): an email is found by its blind index (exact match,
                # R-51.5); a name is not searchable in SQL.
                pattern = f"%{_like_escape(q.strip()[:100])}%"
                email_index = self._keys.blind_index(conn, q) if "@" in q else None
                where += (
                    " and (e.action ilike %s or u.email_blind_index = %s or e.target_id ilike %s"
                    f" or (e.meta->>'title' ilike %s and {visible})"
                    " or e.meta->>'outcome' ilike %s or e.meta->>'reason' ilike %s)"
                )
                args += [pattern, email_index, pattern, pattern, *visible_args, pattern, pattern]
            if before is not None:
                where += " and e.id < %s"
                args.append(before)
            rows = conn.execute(
                "select e.id, e.created_at, e.action, e.target_type, e.target_id, e.meta as payload,"  # noqa: S608 - WHERE fragments are fixed SQL from _scope/_title_visible; values bound
                f" e.hash, e.prev_hash, e.actor_id, u.email_ct, u.name_ct, {visible} as title_visible"
                " from audit_events e left join users u on u.id = e.actor_id"
                f" where {where} order by e.id desc limit %s",
                [*visible_args, *args, min(max(limit, 1), 500)],
            ).fetchall()
            out = [self._redact(p, self._actor(conn, r)) for r in rows]
            people = {u for e in out for u in e["payload"].get("shared_with", [])}
            names: dict[str, str] = {}
            if people:
                for r in conn.execute(
                    "select id, name_ct, email_ct from users where id = any(%s::uuid[])",
                    [list(people)],
                ).fetchall():
                    person = self._keys.open_contact_row(conn, dict(r))
                    names[str(r["id"])] = person["name"] or person["email"] or "User"
        for e in out:
            if e["payload"].get("shared_with"):
                e["shared_with_names"] = [names.get(u, "User") for u in e["payload"]["shared_with"]]
        return out

    def _actor(self, conn: Any, row: dict[str, Any]) -> dict[str, Any]:
        """The row with the actor's decrypted email and name (`actor_email`, `actor_name`)."""
        r = dict(row)
        person = (
            self._keys.open_contact_row(conn, r, user_key="actor_id")
            if r["actor_id"] is not None
            else {"email": None, "name": None}
        )
        r["actor_email"], r["actor_name"] = person.get("email"), person.get("name")
        return r

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
        """Recompute every chain of the organization (each workspace and the control chain); report only the
        count visible to this role."""
        m = p.membership
        assert m is not None
        where, args = self._scope(p)
        with self._db.as_service("audit", p) as conn:
            status = lmqa_audit.verify_chain(conn, m.org_id)
            row = conn.execute(
                f"select count(*) as n from audit_events e where {where}",  # noqa: S608 - fixed SQL from _scope
                args,
            ).fetchone()
        assert row is not None
        return {
            "ok": status.ok,
            "checked": status.checked,
            "events_in_scope": int(row["n"]),
            # Event IDs outside a member's own view are not theirs to see.
            "first_bad_id": status.first_bad_id if m.role != "tenant" else None,
        }
