"""Identity, onboarding and lifecycle (blueprint 5, 6, 7).

Path A: create an organization (the creator becomes its Super Admin).
Path B: join as admin with the 64-character Organization Code. The membership stays `pending_approval` and the
        workspace `pending` until the Super Admin approves (a leaked code is then a nuisance request, not a
        takeover); approval moves the workspace pending -> provisioning -> active.
Path C: join as tenant with the 32-character Admin Code; `pending_approval` until the admin approves. A preview
        shows what the code joins without consuming a use.
A membership's role never changes (R-1 criterion 8, enforced by the database too): a person who needs another role
is removed and onboards again. The MVP API still reports `pending_approval` as `pending` (`wire_status`).
The role comes from the kind of code, never from the client. Every code failure returns one identical error;
the true reason goes to the audit log only. Transitions come from contracts/state-machines.yaml.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql

import lmqa_audit
from identity.ratelimit import SlidingWindow
from lmqa_db import Claims, Database, Row
from lmqa_keys import Field, FieldCipher, KeyProviderError, field_cipher_from_settings
from lmqa_models.contracts import Machine, feature_enabled
from lmqa_models.errors import BadRequest, Conflict, NotFound, ServiceError, TooManyRequests
from lmqa_models.principal import Membership, Principal
from lmqa_models.settings import ConfigError, Settings
from lmqa_security import codes

log = logging.getLogger(__name__)
MEMBERSHIP = Machine.load("membership")
WORKSPACE = Machine.load("workspace")

PHONE = re.compile(r"[0-9+()\- ]{3,40}")
PROFILE_FIELDS = ("name", "job_title", "department", "phone")
CONTACT_FIELDS = frozenset(
    {"email", "name", "phone"}
)  # encrypted: users.<field>_ct (lmqa_keys, R-51.3)

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
    where m.user_id = %s and m.status in ('pending_approval', 'active', 'suspended')
    order by m.created_at desc limit 1
"""


def wire_status(status: str) -> str:
    """The membership state as the MVP API and frontend name it: section 6.2 `pending_approval` is `pending`."""
    return "pending" if status == "pending_approval" else status


def _move_workspace(
    conn: psycopg.Connection[Row], workspace_id: object, current: str, to: str
) -> None:
    """Move an admin's workspace along the `workspace` machine (6.3) as the Super Admin. The MVP has nothing to
    provision, so approval runs pending -> provisioning -> active in one transaction; the database refuses
    pending -> active."""
    steps = ["provisioning", "active"] if (current, to) == ("pending", "active") else [to]
    for step in steps:
        if step == current:
            continue
        WORKSPACE.check("super_admin", current, step, {"org_active": True, "provisioned": True})
        conn.execute(
            "update workspaces set status = %s, state_changed_at = now() where id = %s",
            [step, workspace_id],
        )
        current = step


def _actor(p: Principal, target: Row) -> str:
    """The caller's relation to a membership row, in the actor names of contracts/state-machines.yaml."""
    m = p.membership
    if str(target["user_id"]) == p.user_id:
        return "member"
    if m is not None and m.status == "active":
        if (
            target["role"] == "admin"
            and m.role == "super_admin"
            and m.org_id == str(target["org_id"])
        ):
            return "approver"
        if (
            target["role"] == "tenant"
            and m.role == "admin"
            and m.workspace_id == str(target["workspace_id"])
        ):
            return "approver"
    return "other"


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
    def __init__(self, settings: Settings, db: Database, keys: FieldCipher | None = None) -> None:
        self._s = settings
        self._db = db
        self.keys = keys or field_cipher_from_settings()
        self._fail_user = SlidingWindow(5, 15 * 60)  # blueprint 7.6 rate limits
        self._fail_ip = SlidingWindow(20, 60 * 60)

    # ------------------------------------------------------------------ keys
    def ensure_keys(self, org_id: str, workspace_id: str | None = None) -> None:
        """Provision the organization CMK, the workspace content key and this month's audit keys (R-51.2), in
        their own committed transaction. Idempotent; also the field cipher's provisioner for a workspace that has
        no key yet (the identity role holds the key-table grants)."""
        ring = self.keys.ring
        month = datetime.now(UTC).date()
        with self._db.as_service("identity", Claims(actor="identity:keys")) as conn:
            ring.ensure_org_key(conn, org_id)
            ring.ensure_audit_key(conn, org_id, None, month)
            if workspace_id:
                ring.ensure_workspace_key(conn, org_id, workspace_id)
                ring.ensure_audit_key(conn, org_id, workspace_id, month)

    def _provision_after(self, org_id: Any, workspace_id: Any = None) -> None:
        """Best effort after a commit: a key provider outage must not undo onboarding; the field cipher provisions
        the keys on first use instead."""
        try:
            self.ensure_keys(str(org_id), str(workspace_id) if workspace_id else None)
        except KeyProviderError:
            log.warning(
                "key provisioning for organization %s deferred: key provider unavailable", org_id
            )

    def open_people(
        self, conn: Any, rows: list[Row], *, user_key: str = "user_id"
    ) -> list[dict[str, Any]]:
        """Rows with email_ct/name_ct/phone_ct replaced by the decrypted email, name and phone."""
        out = []
        for r in rows:
            item = self.keys.open_contact_row(conn, dict(r), user_key=user_key)
            out.append({k: v for k, v in item.items() if not k.endswith("_ct")})
        return out

    def _contact(self, conn: Any, user_id: Any, field: str, value: str | None) -> bytes | None:
        return self.keys.seal(conn, Field.contact(f"user.{field}", user_id), value)

    # ------------------------------------------------------------------ principal
    def known_email(self, sub: str) -> bool:
        with self._db.as_service("identity", Claims(actor="identity:login")) as conn:
            row = conn.execute("select email_ct from users where auth0_sub = %s", [sub]).fetchone()
        return bool(row and row["email_ct"])

    def resolve(self, sub: str, email: str | None, name: str | None) -> Principal:
        """The user row for an Auth0 subject, created on first sight. Contact fields are sealed under the user's ID
        (associated data), so the ID is chosen here, before the row exists."""
        with self._db.as_service("identity", Claims(actor="identity:login")) as conn:
            conn.execute(
                "insert into users (id, auth0_sub, last_seen_at) values (%s, %s, now())"
                " on conflict (auth0_sub) do nothing",
                [uuid.uuid4(), sub],
            )
            user = conn.execute(
                "select id, email_ct, name_ct, profile_updated_at, last_seen_at < now() - interval '1 minute' as stale"
                " from users where auth0_sub = %s for update",
                [sub],
            ).fetchone()
            assert user is not None
            uid = user["id"]
            current = self.keys.open_contact_row(conn, dict(user))
            new_email = email or current["email"]
            # A name the person set on their Profile page wins over the Auth0 name.
            new_name = current["name"] if user["profile_updated_at"] else (name or current["name"])
            if (new_email, new_name) != (current["email"], current["name"]) or user["stale"]:
                conn.execute(
                    "update users set email_ct = %s, email_blind_index = %s, name_ct = %s, last_seen_at = now()"
                    " where id = %s",
                    [
                        self._contact(conn, uid, "email", new_email)
                        if new_email != current["email"]
                        else user["email_ct"],
                        self.keys.blind_index(conn, new_email),
                        self._contact(conn, uid, "name", new_name)
                        if new_name != current["name"]
                        else user["name_ct"],
                        uid,
                    ],
                )
            membership = _membership(conn.execute(MEMBERSHIP_SQL, [uid]).fetchone())
        return Principal(str(uid), sub, new_email, new_name, membership)

    @staticmethod
    def me(p: Principal) -> dict[str, Any]:
        m = p.membership
        membership = None
        if m is not None:
            membership = {
                "id": m.id,
                "role": m.role,
                "status": wire_status(m.status),
                "active": m.active,
                "organization": {
                    "id": m.org_id,
                    "name": m.org_name,
                    "kind": m.org_kind,
                    "status": m.org_status,
                },
                "workspace": None
                if m.workspace_id is None
                else {"id": m.workspace_id, "name": m.workspace_name, "status": m.workspace_status},
            }
        return {
            "user": {"id": p.user_id, "email": p.email, "name": p.name},
            "membership": membership,
        }

    # ------------------------------------------------------------------ profile
    def profile(self, p: Principal) -> dict[str, Any]:
        m = p.membership
        assert m is not None
        with self._db.as_service("identity", Claims(actor="identity:login")) as conn:
            row = conn.execute(
                "select u.id, u.email_ct, u.name_ct, u.job_title, u.department, u.phone_ct, u.profile_updated_at,"
                " u.created_at, m.created_at as joined_at, m.decided_at as approved_at"
                " from users u join memberships m on m.user_id = u.id where u.id = %s and m.id = %s",
                [p.user_id, m.id],
            ).fetchone()
            assert row is not None
            person = self.open_people(conn, [row], user_key="id")[0]
        person.pop("id")
        return {
            **jsonable(person),
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
                    raise BadRequest(
                        "Phone may contain digits, spaces and + ( ) - only (up to 40 characters)."
                    )
            elif len(text) > 120:
                raise BadRequest(
                    f"{field.replace('_', ' ').capitalize()} is limited to 120 characters."
                )
            clean[field] = text or None
        if not clean:
            return self.profile(p)
        with self._db.as_service("identity", p) as conn:
            row = conn.execute(
                "select id, name_ct, job_title, department, phone_ct from users where id = %s for update",
                [p.user_id],
            ).fetchone()
            assert row is not None
            before = self.open_people(conn, [row], user_key="id")[0]
            changed = sorted(f for f, v in clean.items() if before[f] != v)
            if changed:
                # Column names come from PROFILE_FIELDS only; contact fields are stored sealed (<field>_ct).
                columns = [f"{f}_ct" if f in CONTACT_FIELDS else f for f in changed]
                values = [
                    self._contact(conn, p.user_id, f, clean[f]) if f in CONTACT_FIELDS else clean[f]
                    for f in changed
                ]
                assignments = sql.SQL(", ").join(
                    sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns
                )
                conn.execute(
                    sql.SQL("update users set {}, profile_updated_at = now() where id = %s").format(
                        assignments
                    ),
                    [*values, p.user_id],
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
        with self._db.as_service("identity", p) as conn:
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
        self._provision_after(org["id"])
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
        with self._db.as_service("identity", p) as conn:
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
        with self._db.as_service("identity", p) as conn:
            row = conn.execute(
                "select lookup_id, created_at, expires_at, max_uses, uses from join_codes where org_id = %s"
                " and kind = %s and workspace_id is not distinct from %s and revoked_at is null"
                " order by created_at desc limit 1",
                [m.org_id, kind, workspace_id],
            ).fetchone()
        return None if row is None else {"lookup_id": row["lookup_id"], **_code_meta(row)}

    def _redeem(  # noqa: C901, PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        conn: psycopg.Connection[Row],
        p: Principal,
        ip: str,
        raw: str,
        kind: codes.Kind,
        *,
        consume: bool,
    ) -> Row:
        if self._fail_user.blocked(p.user_id) or self._fail_ip.blocked(ip):
            raise TooManyRequests("Too many attempts. Try again later.")
        code = codes.parse(raw, kind)
        row = None
        if code is not None:
            row = conn.execute(
                "select c.*, w.status as workspace_status, w.name as workspace_name, o.name as org_name,"  # noqa: S608 - columns allow-listed by PROFILE_FIELDS; values bound
                " o.status as org_status from join_codes c join organizations o on o.id = c.org_id"
                " left join workspaces w on w.id = c.workspace_id"
                " where c.lookup_id = %s and c.kind = %s" + (" for update of c" if consume else ""),
                [code[: codes.LOOKUP_LEN], kind],
            ).fetchone()
        # Constant-time comparison; burns the same work when no row exists (blueprint 7.6).
        valid = code is not None and codes.matches(
            self._pepper(), kind, code, row["code_hmac"] if row else None
        )
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
            elif row["org_status"] != "active" or (
                kind == "admin" and row["workspace_status"] != "active"
            ):
                reason = "scope_inactive"
        if reason is not None or row is None:
            self._fail_user.hit(p.user_id)
            self._fail_ip.hit(ip)
            if row is not None and valid:
                with self._db.as_service(
                    "identity", p
                ) as log_conn:  # own transaction: the caller's rolls back
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
            raise CodeInvalid
        if consume:
            conn.execute("update join_codes set uses = uses + 1 where id = %s", [row["id"]])
        return row

    # ------------------------------------------------------------------ path B
    def join_admin(
        self, p: Principal, ip: str, raw_code: str, workspace_name: str
    ) -> dict[str, Any]:
        self._require_no_membership(p)
        name = _clean_name(workspace_name, "Workspace name")
        with self._db.as_service("identity", p) as conn:
            row = self._redeem(conn, p, ip, raw_code, "org", consume=True)
            ws = conn.execute(
                "insert into workspaces (org_id, name, status) values (%s, %s, 'pending') returning id",
                [row["org_id"], name],
            ).fetchone()
            assert ws is not None
            try:
                conn.execute(
                    "insert into memberships (user_id, org_id, workspace_id, role, status)"
                    " values (%s, %s, %s, 'admin', 'pending_approval')",
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
                payload={"lookup_id": row["lookup_id"]},
            )
        self._provision_after(row["org_id"], ws["id"])
        return {"status": "pending", "organization": row["org_name"]}

    # ------------------------------------------------------------------ path C
    def preview_tenant(self, p: Principal, ip: str, raw_code: str) -> dict[str, Any]:
        with self._db.as_service("identity", p) as conn:
            row = self._redeem(conn, p, ip, raw_code, "admin", consume=False)
            found = conn.execute(
                "select u.id as user_id, u.name_ct, u.email_ct from memberships m join users u on u.id = m.user_id"
                " where m.workspace_id = %s and m.role = 'admin' and m.status = 'active'",
                [row["workspace_id"]],
            ).fetchone()
            admin = self.open_people(conn, [found])[0] if found else None
        return {
            "organization": row["org_name"],
            "workspace": row["workspace_name"],
            "admin": (admin["name"] or admin["email"]) if admin else None,
        }

    def join_tenant(self, p: Principal, ip: str, raw_code: str) -> dict[str, Any]:
        self._require_no_membership(p)
        with self._db.as_service("identity", p) as conn:
            row = self._redeem(conn, p, ip, raw_code, "admin", consume=True)
            try:
                conn.execute(
                    "insert into memberships (user_id, org_id, workspace_id, role, status)"
                    " values (%s, %s, %s, 'tenant', 'pending_approval')",
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
        if m is None or m.status != "pending_approval":
            raise NotFound("No pending request.")
        with self._db.as_service("identity", p) as conn:
            # Nobody changes their own membership (6.2, R-10.5), so a withdrawal is no state change: the request
            # that was never approved is deleted, with an admin's pending workspace (6.3 "removed on reject"). The
            # database allows the member this delete only while the row is pending_approval.
            conn.execute(
                "delete from memberships where id = %s and status = 'pending_approval'", [m.id]
            )
            if m.role == "admin":
                conn.execute(
                    "delete from workspaces where id = %s and status = 'pending'", [m.workspace_id]
                )
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
        """The Super Admin reads usage only from `workspace_usage` (R-3 criterion 3): tenant rows and content tables
        are outside its policy set. Document and question counts are the frozen `usage_counts` feature."""
        m = p.membership
        assert m is not None
        usage = (
            ", coalesce(wu.documents, 0) as documents, coalesce(wu.queries, 0) as queries"
            if feature_enabled("usage_counts")
            else ""
        )
        with self._db.as_service("identity", p) as conn:
            rows = conn.execute(
                f"""
                select m.id, m.user_id, m.status, m.created_at, m.decided_at, u.email_ct, u.name_ct,
                       u.last_seen_at, w.id as workspace_id, w.name as workspace_name, w.status as workspace_status,
                       coalesce(wu.tenants, 0) as tenants{usage}
                from memberships m join users u on u.id = m.user_id join workspaces w on w.id = m.workspace_id
                left join workspace_usage wu on wu.org_id = w.org_id and wu.workspace_id = w.id
                where m.org_id = %s and m.role = 'admin' and m.status in ('pending_approval', 'active', 'suspended')
                order by (m.status = 'pending_approval') desc, m.created_at
                """,  # noqa: S608 - `usage` is one of two constant strings; values bound
                [m.org_id],
            ).fetchall()
            people = self.open_people(conn, rows)
        return [{**jsonable(r), "status": wire_status(r["status"])} for r in people]

    def _decide(  # noqa: PLR0913, PLR0917 - one linear flow shared by both {action} routes
        self,
        conn: psycopg.Connection[Row],
        p: Principal,
        target: Row | None,
        route: str,
        action: str,
        what: str,
    ) -> tuple[Row, str]:
        """Check one {action} request against the route view and the `membership` machine (R-10.5, R-10.4)."""
        t = Machine.load(route).action(action)
        if t is None:
            raise NotFound("Unknown action.")
        if target is None:
            raise NotFound(f"{what} not found.")
        if target["status"] != t.from_status:
            raise Conflict(f"Cannot {action} a {what.lower()} whose status is {target['status']}.")
        assert p.membership is not None
        MEMBERSHIP.check(
            _actor(p, target), t.from_status, t.to_status, {"approver_active": p.membership.active}
        )
        conn.execute(
            "update memberships set status = %s, decided_at = now(), approver_id = %s where id = %s",
            [t.to_status, p.user_id, target["id"]],
        )
        return target, t.to_status

    def decide_admin(self, p: Principal, membership_id: str, action: str) -> dict[str, Any]:
        sa = p.membership
        assert sa is not None
        route = Machine.load("admin_membership").action(action)
        if route is None:
            raise NotFound("Unknown action.")
        with self._db.as_service("identity", p) as conn:
            target = conn.execute(
                "select m.id, m.user_id, m.org_id, m.workspace_id, m.role, m.status, w.status as workspace_status"
                " from memberships m join workspaces w on w.id = m.workspace_id"
                " where m.id = %s and m.org_id = %s and m.role = 'admin' for update of m",
                [membership_id, sa.org_id],
            ).fetchone()
            target, status = self._decide(conn, p, target, "admin_membership", action, "Admin")
            assert route.workspace_status is not None
            _move_workspace(
                conn, target["workspace_id"], target["workspace_status"], route.workspace_status
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
        return {"id": membership_id, "status": status, "workspace_status": route.workspace_status}

    # ------------------------------------------------------------------ Admin: Manage Tenants
    def list_members(self, p: Principal) -> list[dict[str, Any]]:
        """Membership and profile columns only. svc_identity has no grant on content tables, and the design defines
        no per-member usage source, so the frozen per-member counts (`usage_counts`) are not produced here."""
        m = p.membership
        assert m is not None
        with self._db.as_service("identity", p) as conn:
            rows = conn.execute(
                """
                select m.id, m.user_id, m.status, m.created_at, m.decided_at, u.email_ct, u.name_ct,
                       u.last_seen_at, u.job_title, u.department, u.phone_ct, u.profile_updated_at
                from memberships m join users u on u.id = m.user_id
                where m.workspace_id = %s and m.role = 'tenant'
                  and m.status in ('pending_approval', 'active', 'suspended')
                order by (m.status = 'pending_approval') desc, m.created_at
                """,
                [m.workspace_id],
            ).fetchall()
            people = self.open_people(conn, rows)
        return [{**jsonable(r), "status": wire_status(r["status"])} for r in people]

    def decide_member(self, p: Principal, membership_id: str, action: str) -> dict[str, Any]:
        admin = p.membership
        assert admin is not None
        with self._db.as_service("identity", p) as conn:
            target = conn.execute(
                "select id, user_id, org_id, workspace_id, role, status from memberships"
                " where id = %s and workspace_id = %s and role = 'tenant' for update",
                [membership_id, admin.workspace_id],
            ).fetchone()
            _, status = self._decide(conn, p, target, "tenant_membership", action, "Member")
            lmqa_audit.append(
                conn,
                org_id=admin.org_id,
                workspace_id=admin.workspace_id,
                actor_id=p.user_id,
                action=f"tenant.{action}",
                target_type="membership",
                target_id=membership_id,
            )
        return {"id": membership_id, "status": status}
