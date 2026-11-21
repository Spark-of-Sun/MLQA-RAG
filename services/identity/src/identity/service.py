"""Identity, onboarding and lifecycle (blueprint 5, 6, 7).

Path A: create an organization (the creator becomes its Super Admin).
Path B: join as admin with the 64-character Organization Code. Membership and workspace stay `pending` until
        the Super Admin approves (a leaked code is then a nuisance request, not a takeover).
Path C: join as tenant with the 32-character Admin Code; `pending` until the admin approves. A preview shows
        what the code joins without consuming a use.
The role comes from the kind of code, never from the client. Every code failure returns one identical error;
the true reason goes to the audit log only. Transitions come from contracts/state-machines.yaml.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg

import lmqa_audit
from identity.ratelimit import SlidingWindow
from lmqa_db import Database, Row
from lmqa_models.contracts import transition
from lmqa_models.errors import BadRequest, Conflict, NotFound, ServiceError, TooManyRequests
from lmqa_models.principal import Membership, Principal
from lmqa_models.settings import ConfigError, Settings
from lmqa_security import codes

PHONE = re.compile(r"[0-9+()\- ]{3,40}")
PROFILE_FIELDS = ("name", "job_title", "department", "phone")

CODE_POLICY: dict[codes.Kind, tuple[timedelta, int]] = {  # blueprint 7.6: expiry / max uses
    "org": (timedelta(days=30), 25),
    "admin": (timedelta(days=90), 100),
}

MEMBERSHIP_SQL = """
    select m.id, m.role, m.status, m.org_id, o.name as org_name, o.kind as org_kind, o.status as org_status,
           m.workspace_id, w.name as workspace_name, w.status as workspace_status
    from memberships m
    join organizations o on o.id = m.org_id
    left join workspaces w on w.id = m.workspace_id
    where m.user_id = %s and m.status <> 'rejected'
    order by m.created_at desc limit 1
"""


class CodeInvalid(ServiceError):
    status = 400

    def __init__(self) -> None:
        super().__init__("Code invalid or expired.")


def _membership(row: Row | None) -> Membership | None:
    if row is None:
        return None
    return Membership(
        id=str(row["id"]),
        role=row["role"],
        status=row["status"],
        org_id=str(row["org_id"]),
        org_name=row["org_name"],
        org_kind=row["org_kind"],
        org_status=row["org_status"],
        workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
        workspace_name=row["workspace_name"],
        workspace_status=row["workspace_status"],
    )


def _clean_name(value: str, what: str) -> str:
    name = " ".join(value.split())
    if not 2 <= len(name) <= 120:
        raise BadRequest(f"{what} must be between 2 and 120 characters.")
    return name


def jsonable(row: Row) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, UUID):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _code_meta(row: Row) -> dict[str, Any]:
    return {
        "created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "max_uses": row["max_uses"],
        "uses": row["uses"],
    }


class IdentityService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self._s = settings
        self._db = db
        self._fail_user = SlidingWindow(5, 15 * 60)  # blueprint 7.6 rate limits
        self._fail_ip = SlidingWindow(20, 60 * 60)

    # ------------------------------------------------------------------ principal
    def known_email(self, sub: str) -> bool:
        with self._db.system() as conn:
            row = conn.execute("select email from users where auth0_sub = %s", [sub]).fetchone()
        return bool(row and row["email"])

    def resolve(self, sub: str, email: str | None, name: str | None) -> Principal:
        with self._db.system() as conn:
            user = conn.execute(
                "insert into users (auth0_sub, email, name, last_seen_at) values (%s, %s, %s, now())"
                " on conflict (auth0_sub) do update set email = coalesce(excluded.email, users.email),"
                # A name the person set on their Profile page wins over the Auth0 name.
                " name = case when users.profile_updated_at is null then coalesce(excluded.name, users.name)"
                " else users.name end,"
                " last_seen_at = case when users.last_seen_at < now() - interval '1 minute' then now()"
                " else users.last_seen_at end"
                " returning id, email, name",
                [sub, email, name],
            ).fetchone()
            assert user is not None
            membership = _membership(conn.execute(MEMBERSHIP_SQL, [user["id"]]).fetchone())
        return Principal(str(user["id"]), sub, user["email"], user["name"], membership)

    @staticmethod
    def me(p: Principal) -> dict[str, Any]:
        m = p.membership
        membership = None
        if m is not None:
            membership = {
                "id": m.id,
                "role": m.role,
                "status": m.status,
                "active": m.active,
                "organization": {"id": m.org_id, "name": m.org_name, "kind": m.org_kind, "status": m.org_status},
                "workspace": None
                if m.workspace_id is None
                else {"id": m.workspace_id, "name": m.workspace_name, "status": m.workspace_status},
            }
        return {"user": {"id": p.user_id, "email": p.email, "name": p.name}, "membership": membership}

    # ------------------------------------------------------------------ profile
    def profile(self, p: Principal) -> dict[str, Any]:
        m = p.membership
        assert m is not None
        with self._db.system() as conn:
            row = conn.execute(
                "select u.email, u.name, u.job_title, u.department, u.phone, u.profile_updated_at, u.created_at,"
                " m.created_at as joined_at, m.decided_at as approved_at"
                " from users u join memberships m on m.user_id = u.id where u.id = %s and m.id = %s",
                [p.user_id, m.id],
            ).fetchone()
        assert row is not None
        return {
            **jsonable(row),
            "role": m.role,
            "organization": m.org_name,
            "workspace": m.workspace_name,
        }

    def update_profile(self, p: Principal, changes: dict[str, str | None]) -> dict[str, Any]:
        m = p.membership
        assert m is not None
        clean: dict[str, str | None] = {}
        for field, value in changes.items():
            if field not in PROFILE_FIELDS:  # column names are interpolated below: allow-list only
                raise BadRequest(f"Unknown profile field {field!r}.")
            text = " ".join(value.split()) if value else ""
            if field == "name":
                if not 2 <= len(text) <= 120:
                    raise BadRequest("Name must be between 2 and 120 characters.")
            elif field == "phone":
                if text and not PHONE.fullmatch(text):
                    raise BadRequest("Phone may contain digits, spaces and + ( ) - only (up to 40 characters).")
            elif len(text) > 120:
                raise BadRequest(f"{field.replace('_', ' ').capitalize()} is limited to 120 characters.")
            clean[field] = text or None
        if not clean:
            return self.profile(p)
        with self._db.system() as conn:
            before = conn.execute(
                "select name, job_title, department, phone from users where id = %s for update", [p.user_id]
            ).fetchone()
            assert before is not None
            changed = sorted(f for f, v in clean.items() if before[f] != v)
            if changed:
                assignments = ", ".join(f"{f} = %s" for f in changed)
                conn.execute(
                    f"update users set {assignments}, profile_updated_at = now() where id = %s",
                    [*(clean[f] for f in changed), p.user_id],
                )
                lmqa_audit.append(
                    conn,
                    org_id=m.org_id,
                    workspace_id=m.workspace_id,
                    actor_id=p.user_id,
                    action="profile.updated",
                    target_type="user",
                    target_id=p.user_id,
                    payload={"fields": changed},
                )
        return self.profile(p)

    @staticmethod
    def _require_no_membership(p: Principal) -> None:
        if p.membership is not None:
            raise Conflict("You already have a membership. One membership per person is supported.")

    # ------------------------------------------------------------------ path A
    def create_organization(self, p: Principal, name: str, kind: str) -> dict[str, Any]:
        self._require_no_membership(p)
        if kind not in {"legal", "medical", "both"}:
            raise BadRequest("Organization type must be legal, medical or both.")
        org_name = _clean_name(name, "Organization name")
        with self._db.system() as conn:
            try:
                org = conn.execute(
                    "insert into organizations (name, kind, created_by) values (%s, %s, %s) returning id",
                    [org_name, kind, p.user_id],
                ).fetchone()
                assert org is not None
                conn.execute(
                    "insert into memberships (user_id, org_id, role, status, decided_at)"
                    " values (%s, %s, 'super_admin', 'active', now())",
                    [p.user_id, org["id"]],
                )
            except psycopg.errors.UniqueViolation as exc:
                raise Conflict("You already have a membership.") from exc
            lmqa_audit.append(
                conn,
                org_id=org["id"],
                actor_id=p.user_id,
                action="org.created",
                target_type="organization",
                target_id=org["id"],
                payload={"kind": kind},
            )
        return {"organization_id": str(org["id"])}

    # ------------------------------------------------------------------ codes
    def _pepper(self) -> str:
        if not self._s.code_pepper:
            raise ConfigError("CODE_PEPPER_V1 is not set. Run: make setup")
        return self._s.code_pepper

    def generate_code(self, p: Principal, kind: codes.Kind) -> dict[str, Any]:
        """Rotate: revoke the scope's previous code, create a new one, return the plaintext once."""
        m = p.membership
        assert m is not None
        new = codes.generate(kind)
        ttl, max_uses = CODE_POLICY[kind]
        workspace_id = m.workspace_id if kind == "admin" else None
        with self._db.system() as conn:
            conn.execute(
                "update join_codes set revoked_at = now() where org_id = %s and kind = %s"
                " and workspace_id is not distinct from %s and revoked_at is null",
                [m.org_id, kind, workspace_id],
            )
            row = conn.execute(
                "insert into join_codes (kind, lookup_id, code_hmac, pepper_id, org_id, workspace_id, created_by,"
                " expires_at, max_uses) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " returning created_at, expires_at, max_uses, uses",
                [
                    kind,
                    new.lookup_id,
                    codes.code_hmac(self._pepper(), kind, new.code),
                    self._s.code_pepper_id,
                    m.org_id,
                    workspace_id,
                    p.user_id,
                    datetime.now(UTC) + ttl,
                    max_uses,
                ],
            ).fetchone()
            assert row is not None
            lmqa_audit.append(
                conn,
                org_id=m.org_id,
                workspace_id=workspace_id,
                actor_id=p.user_id,
                action=f"code.{kind}.rotated",
                target_type="join_code",
                target_id=new.lookup_id,
            )
        return {"code": new.display, "lookup_id": new.lookup_id, **_code_meta(row)}

    def code_info(self, p: Principal, kind: codes.Kind) -> dict[str, Any] | None:
        m = p.membership
        assert m is not None
        workspace_id = m.workspace_id if kind == "admin" else None
        with self._db.system() as conn:
            row = conn.execute(
                "select lookup_id, created_at, expires_at, max_uses, uses from join_codes where org_id = %s"
                " and kind = %s and workspace_id is not distinct from %s and revoked_at is null"
                " order by created_at desc limit 1",
                [m.org_id, kind, workspace_id],
            ).fetchone()
        return None if row is None else {"lookup_id": row["lookup_id"], **_code_meta(row)}

    def _redeem(
        self, conn: psycopg.Connection[Row], p: Principal, ip: str, raw: str, kind: codes.Kind, *, consume: bool
    ) -> Row:
        if self._fail_user.blocked(p.user_id) or self._fail_ip.blocked(ip):
            raise TooManyRequests("Too many attempts. Try again later.")
        code = codes.parse(raw, kind)
        row = None
        if code is not None:
            row = conn.execute(
                "select c.*, w.status as workspace_status, w.name as workspace_name, o.name as org_name,"
                " o.status as org_status from join_codes c join organizations o on o.id = c.org_id"
                " left join workspaces w on w.id = c.workspace_id"
                " where c.lookup_id = %s and c.kind = %s" + (" for update of c" if consume else ""),
                [code[: codes.LOOKUP_LEN], kind],
            ).fetchone()
        # Constant-time comparison; burns the same work when no row exists (blueprint 7.6).
        valid = code is not None and codes.matches(self._pepper(), kind, code, row["code_hmac"] if row else None)
        reason = None
        if not valid:
            reason = "format" if code is None else "mismatch"
        elif row is not None:
            if row["revoked_at"] is not None:
                reason = "revoked"
            elif row["expires_at"] <= datetime.now(UTC):
                reason = "expired"
            elif row["uses"] >= row["max_uses"]:
                reason = "exhausted"
            elif row["org_status"] != "active" or (kind == "admin" and row["workspace_status"] != "active"):
                reason = "scope_inactive"
        if reason is not None or row is None:
            self._fail_user.hit(p.user_id)
            self._fail_ip.hit(ip)
            if row is not None and valid:
                with self._db.system() as log_conn:  # own transaction: the caller's rolls back
                    lmqa_audit.append(
                        log_conn,
                        org_id=row["org_id"],
                        workspace_id=row["workspace_id"],
                        actor_id=p.user_id,
                        action="code.rejected",
                        target_type="join_code",
                        target_id=row["lookup_id"],
                        payload={"reason": reason},
                    )
            raise CodeInvalid()
        if consume:
            conn.execute("update join_codes set uses = uses + 1 where id = %s", [row["id"]])
        return row

    # ------------------------------------------------------------------ path B
    def join_admin(self, p: Principal, ip: str, raw_code: str, workspace_name: str) -> dict[str, Any]:
        self._require_no_membership(p)
        name = _clean_name(workspace_name, "Workspace name")
        with self._db.system() as conn:
            row = self._redeem(conn, p, ip, raw_code, "org", consume=True)
            ws = conn.execute(
                "insert into workspaces (org_id, name, status) values (%s, %s, 'pending') returning id",
                [row["org_id"], name],
            ).fetchone()
            assert ws is not None
            try:
                conn.execute(
                    "insert into memberships (user_id, org_id, workspace_id, role, status)"
                    " values (%s, %s, %s, 'admin', 'pending')",
                    [p.user_id, row["org_id"], ws["id"]],
                )
            except psycopg.errors.UniqueViolation as exc:
                raise Conflict("You already have a membership.") from exc
            lmqa_audit.append(
                conn,
                org_id=row["org_id"],
                actor_id=p.user_id,
                action="admin.join_requested",
                target_type="workspace",
                target_id=ws["id"],
                payload={"code": row["lookup_id"], "workspace": name},
            )
        return {"status": "pending", "organization": row["org_name"]}

    # ------------------------------------------------------------------ path C
    def preview_tenant(self, p: Principal, ip: str, raw_code: str) -> dict[str, Any]:
        with self._db.system() as conn:
            row = self._redeem(conn, p, ip, raw_code, "admin", consume=False)
            admin = conn.execute(
                "select u.name, u.email from memberships m join users u on u.id = m.user_id"
                " where m.workspace_id = %s and m.role = 'admin' and m.status = 'active'",
                [row["workspace_id"]],
            ).fetchone()
        return {
            "organization": row["org_name"],
            "workspace": row["workspace_name"],
            "admin": (admin["name"] or admin["email"]) if admin else None,
        }

    def join_tenant(self, p: Principal, ip: str, raw_code: str) -> dict[str, Any]:
        self._require_no_membership(p)
        with self._db.system() as conn:
            row = self._redeem(conn, p, ip, raw_code, "admin", consume=True)
            try:
                conn.execute(
                    "insert into memberships (user_id, org_id, workspace_id, role, status)"
                    " values (%s, %s, %s, 'tenant', 'pending')",
                    [p.user_id, row["org_id"], row["workspace_id"]],
                )
            except psycopg.errors.UniqueViolation as exc:
                raise Conflict("You already have a membership.") from exc
            lmqa_audit.append(
                conn,
                org_id=row["org_id"],
                workspace_id=row["workspace_id"],
                actor_id=p.user_id,
                action="tenant.join_requested",
                target_type="user",
                target_id=p.user_id,
            )
        return {"status": "pending", "workspace": row["workspace_name"]}

    def withdraw(self, p: Principal) -> None:
        m = p.membership
        if m is None or m.status != "pending":
            raise NotFound("No pending request.")
        with self._db.system() as conn:
            conn.execute(
                "update memberships set status = 'rejected', decided_at = now(), decided_by = %s"
                " where id = %s and status = 'pending'",
                [p.user_id, m.id],
            )
            if m.role == "admin":
                conn.execute("update workspaces set status = 'rejected' where id = %s", [m.workspace_id])
            lmqa_audit.append(
                conn,
                org_id=m.org_id,
                workspace_id=m.workspace_id if m.role == "tenant" else None,
                actor_id=p.user_id,
                action=f"{m.role}.request_withdrawn",
                target_type="membership",
                target_id=m.id,
            )

    # ------------------------------------------------------------------ Super Admin: Manage Admins
    def list_admins(self, p: Principal) -> list[dict[str, Any]]:
        m = p.membership
        assert m is not None
        with self._db.system() as conn:
            rows = conn.execute(
                """
                select m.id, m.user_id, m.status, m.created_at, m.decided_at, u.email, u.name, u.last_seen_at,
                       w.id as workspace_id, w.name as workspace_name, w.status as workspace_status,
                       (select count(*) from memberships t where t.workspace_id = w.id and t.role = 'tenant'
                          and t.status = 'active') as tenants,
                       (select count(*) from memberships t where t.workspace_id = w.id and t.role = 'tenant'
                          and t.status = 'pending') as tenants_pending,
                       (select count(*) from documents d where d.workspace_id = w.id) as documents,
                       (select count(*) from queries q where q.workspace_id = w.id
                          and q.created_at > now() - interval '30 days') as queries_30d
                from memberships m join users u on u.id = m.user_id join workspaces w on w.id = m.workspace_id
                where m.org_id = %s and m.role = 'admin' and m.status <> 'rejected'
                order by (m.status = 'pending') desc, m.created_at
                """,
                [m.org_id],
            ).fetchall()
        return [jsonable(r) for r in rows]

    def decide_admin(self, p: Principal, membership_id: str, action: str) -> dict[str, Any]:
        t = transition("admin_membership", action)
        if t is None:
            raise NotFound("Unknown action.")
        sa = p.membership
        assert sa is not None
        with self._db.system() as conn:
            target = conn.execute(
                "select id, workspace_id, status from memberships where id = %s and org_id = %s and role = 'admin'"
                " for update",
                [membership_id, sa.org_id],
            ).fetchone()
            if target is None:
                raise NotFound("Admin not found.")
            if target["status"] != t.from_status:
                raise Conflict(f"Cannot {action} an admin whose status is {target['status']}.")
            conn.execute(
                "update memberships set status = %s, decided_at = now(), decided_by = %s where id = %s",
                [t.to_status, p.user_id, membership_id],
            )
            conn.execute(
                "update workspaces set status = %s where id = %s", [t.workspace_status, target["workspace_id"]]
            )
            lmqa_audit.append(
                conn,
                org_id=sa.org_id,
                actor_id=p.user_id,
                action=f"admin.{action}",
                target_type="membership",
                target_id=membership_id,
                payload={"workspace_id": str(target["workspace_id"])},
            )
        return {"id": membership_id, "status": t.to_status, "workspace_status": t.workspace_status}

    # ------------------------------------------------------------------ Admin: Manage Tenants
    def list_members(self, p: Principal) -> list[dict[str, Any]]:
        m = p.membership
        assert m is not None
        with self._db.system() as conn:
            rows = conn.execute(
                """
                select m.id, m.user_id, m.status, m.created_at, m.decided_at, u.email, u.name, u.last_seen_at,
                       u.job_title, u.department, u.phone, u.profile_updated_at,
                       (select count(*) from documents d where d.workspace_id = m.workspace_id
                          and d.owner_id = m.user_id) as documents,
                       -- Counted, never listed: the admin cannot see these documents.
                       (select count(*) from documents d where d.workspace_id = m.workspace_id
                          and d.owner_id = m.user_id and d.visibility = 'private'
                          and not exists (select 1 from document_shares s where s.document_id = d.id))
                          as private_documents,
                       (select count(*) from document_shares s where s.workspace_id = m.workspace_id
                          and s.owner_id = m.user_id and s.user_id = %(admin)s) as shared_with_you,
                       (select count(*) from document_shares s where s.workspace_id = m.workspace_id
                          and s.owner_id = %(admin)s and s.user_id = m.user_id) as shared_with_them,
                       -- Only the admin can share with the whole workspace, so these reach every member too.
                       (select count(*) from documents d where d.workspace_id = m.workspace_id
                          and d.visibility = 'workspace') as shared_with_workspace,
                       q.questions, q.tokens, q.last_question_at
                from memberships m join users u on u.id = m.user_id
                cross join lateral (
                    select count(*) as questions, coalesce(sum(coalesce(x.tokens_in, 0) + coalesce(x.tokens_out, 0)), 0)
                           as tokens, max(x.created_at) as last_question_at
                    from queries x where x.workspace_id = m.workspace_id and x.user_id = m.user_id
                ) q
                where m.workspace_id = %(ws)s and m.role = 'tenant' and m.status <> 'rejected'
                order by (m.status = 'pending') desc, m.created_at
                """,
                {"ws": m.workspace_id, "admin": p.user_id},
            ).fetchall()
        return [jsonable(r) for r in rows]

    def decide_member(self, p: Principal, membership_id: str, action: str) -> dict[str, Any]:
        t = transition("tenant_membership", action)
        if t is None:
            raise NotFound("Unknown action.")
        admin = p.membership
        assert admin is not None
        with self._db.system() as conn:
            target = conn.execute(
                "select id, status from memberships where id = %s and workspace_id = %s and role = 'tenant' for update",
                [membership_id, admin.workspace_id],
            ).fetchone()
            if target is None:
                raise NotFound("Member not found.")
            if target["status"] != t.from_status:
                raise Conflict(f"Cannot {action} a member whose status is {target['status']}.")
            conn.execute(
                "update memberships set status = %s, decided_at = now(), decided_by = %s where id = %s",
                [t.to_status, p.user_id, membership_id],
            )
            lmqa_audit.append(
                conn,
                org_id=admin.org_id,
                workspace_id=admin.workspace_id,
                actor_id=p.user_id,
                action=f"tenant.{action}",
                target_type="membership",
                target_id=membership_id,
            )
        return {"id": membership_id, "status": t.to_status}
