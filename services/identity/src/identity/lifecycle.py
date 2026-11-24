"""Lifecycle effects, revocation fan-out, notifications and Auth0 reconciliation (blueprint 7.5, 7.7, 7.8, 8.6,
G2.8, G2.11, G2.12, G9.11).

Revocation (8.6) when a membership is suspended or removed, in this order:
  1 the database change (the trigger bumps principal_version and NOTIFYs `lmqa_revocation`);
  2 publish `revocation:principal` on Valkey so every gateway instance drops its cached principal and cuts open
    streams within 2 s (G3.4); the gateway also listens to the PostgreSQL NOTIFY as a fallback (<= 5 s);
  3 Auth0: remove the Organization membership, delete refresh tokens and sessions.
Steps 2 and 3 are retried by the identity worker until they succeed; step 1 alone already denies access, because
every request resolves the principal from PostgreSQL.
"""

from __future__ import annotations

import json
import smtplib
import ssl
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import lmqa_audit
from identity.auth0_mgmt import Auth0Error, Auth0Management
from lmqa_keys import Field, FieldCipher, field_cipher_from_settings

ConnFactory = Callable[[], AbstractContextManager[Any]]
REVOCATION_CHANNEL = "revocation:principal"

TEMPLATES: dict[str, tuple[str, str]] = {
    "admin_request": (
        "A new workspace admin is waiting for approval",
        "Someone asked to join {org} as an admin.",
    ),
    "tenant_request": (
        "A new member is waiting for approval",
        "Someone asked to join your workspace.",
    ),
    "approved": ("Your access was approved", "You can now sign in to {org}."),
    "suspended": ("Your access was suspended", "Your access to {org} has been suspended."),
    "emergency_access_started": (
        "Emergency access was used",
        "A member started emergency access. Review it within 72 hours.",
    ),
    "private_read_enabled": (
        "Admin private reading was enabled",
        "Your workspace admin can now open private documents"
        " in a recorded break-glass session. Each session is listed in your audit history.",
    ),
    "successor_effective": (
        "Your workspace has a new admin",
        "A successor admin now manages your workspace.",
    ),
    "wall_lifted": (
        "Your access changed",
        "An access restriction on one of your matters was lifted.",
    ),
    "co_owner_invited": (
        "You were invited as co-owner",
        "Accept the invitation with your passkey within 72 hours.",
    ),
    "owner_recovery_started": (
        "Owner recovery was requested",
        "An owner recovery was requested for {org}. You can veto it within 72 hours.",
    ),
}


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str | None
    password: str | None
    sender: str

    def __repr__(self) -> str:
        return f"SmtpConfig(host={self.host!r}, port={self.port})"


def smtp_from_env(env: dict[str, str]) -> SmtpConfig | None:
    host = env.get("SMTP_HOST")
    if not host or host.startswith("<"):
        return None
    return SmtpConfig(
        host,
        int(env.get("SMTP_PORT", "587")),
        env.get("SMTP_USER"),
        env.get("SMTP_PASSWORD"),
        env.get("SMTP_FROM", env.get("SMTP_USER") or "no-reply@localhost"),
    )


class Notifier:
    """Outbox-backed mail: `enqueue` writes a row in the caller's transaction; `deliver` sends pending rows."""

    def __init__(
        self, conn: ConnFactory, smtp: SmtpConfig | None, keys: FieldCipher | None = None
    ) -> None:
        self._conn = conn
        self._smtp = smtp
        self._keys = keys

    @staticmethod
    def enqueue(conn: Any, user_id: str, kind: str, variables: dict[str, Any]) -> None:
        if kind not in TEMPLATES:
            raise ValueError(f"unknown notification {kind}")
        conn.execute(
            "insert into notifications (to_user_id, kind, template_vars) values (%s, %s, %s::jsonb)",
            [user_id, kind, json.dumps(variables)],
        )

    def deliver(self, limit: int = 50) -> int:
        if not self._smtp:
            return 0
        keys = self._keys or field_cipher_from_settings()
        sent = 0
        with self._conn() as conn:
            rows = conn.execute(
                "select n.id, n.kind, n.template_vars, u.id as user_id, u.email_ct from notifications n"
                " join users u on u.id = n.to_user_id"
                " where n.state = 'pending' order by n.created_at limit %s for update of n skip locked",
                [limit],
            ).fetchall()
            for row in rows:
                subject, body = TEMPLATES[row["kind"]]
                try:
                    email = keys.open(
                        conn, Field.contact("user.email", row["user_id"]), row["email_ct"]
                    )
                    self._send(
                        str(email),
                        subject,
                        body.format_map(_Safe(row["template_vars"] or {})),
                    )
                    conn.execute(
                        "update notifications set state = 'sent', sent_at = now() where id = %s",
                        [row["id"]],
                    )
                    sent += 1
                except (OSError, smtplib.SMTPException) as exc:
                    conn.execute(
                        "update notifications set attempts = attempts + 1, last_error = %s,"
                        " state = case when attempts >= 9 then 'dead' else 'pending' end where id = %s",
                        [type(exc).__name__, row["id"]],
                    )
        return sent

    def _send(self, to: str, subject: str, body: str) -> None:
        assert self._smtp is not None
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._smtp.sender, to, subject
        msg.set_content(body + "\n\nThis message was sent by Cyte. Do not reply.")
        with smtplib.SMTP(self._smtp.host, self._smtp.port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if self._smtp.user and self._smtp.password:
                smtp.login(self._smtp.user, self._smtp.password)
            smtp.send_message(msg)


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "your organization" if key == "org" else ""


class Revoker:
    def __init__(
        self,
        conn: ConnFactory,
        auth0: Auth0Management | None,
        publish: Callable[[str, str], Any] | None,
    ):
        self._conn = conn
        self._auth0 = auth0
        self._publish = publish

    def fan_out(self, user_id: str) -> dict[str, bool]:
        with self._conn() as conn:
            row = conn.execute(
                "select u.auth0_sub, o.auth0_org_id, m.principal_version, m.status from users u"
                " join memberships m on m.user_id = u.id join organizations o on o.id = m.org_id"
                " where u.id = %s order by m.created_at desc limit 1",
                [user_id],
            ).fetchone()
        if not row:
            return {}
        result = {"published": False, "auth0": False}
        if self._publish:
            self._publish(REVOCATION_CHANNEL, f"{user_id}:{row['principal_version']}")
            result["published"] = True
        if self._auth0 and row["status"] in {"suspended", "removed"}:
            try:
                if row["auth0_org_id"]:
                    self._auth0.remove_member(row["auth0_org_id"], row["auth0_sub"])
                self._auth0.revoke_user_sessions(row["auth0_sub"])
                result["auth0"] = True
            except Auth0Error:
                result["auth0"] = (
                    False  # retried by the worker; the database change already denies access
                )
        return result


# --- governance effects that move people and workspaces -------------------------------------------------------


def successor_transfer_effect(conn: Any, request: dict[str, Any]) -> None:
    """Re-parent a frozen workspace to the pending successor (7.8): new admin active, old admin removed, private
    reading reset to off, tenants that were cascade-suspended restored, notices sent."""
    ws = request["target_id"]
    succ = conn.execute(
        "select id, user_id from memberships where workspace_id = %s and role = 'admin'"
        " and status = 'pending_approval' order by created_at desc limit 1",
        [ws],
    ).fetchone()
    if not succ:
        raise RuntimeError("no pending successor for the workspace")
    conn.execute(
        "update memberships set status = 'removed', state_reason = 'removed' where workspace_id = %s"
        " and role = 'admin' and status in ('active', 'suspended') and id <> %s",
        [ws, succ["id"]],
    )
    conn.execute(
        "update memberships set status = 'active', state_reason = 'successor_effective' where id = %s"
        " and status = 'pending_approval'",
        [succ["id"]],
    )
    conn.execute(
        "update workspaces set admin_user_id = %s, admin_can_read_private = false,"
        " status = 'active', state_changed_at = now() where id = %s and status = 'frozen'",
        [succ["user_id"], ws],
    )
    conn.execute(
        "update memberships set status = 'active', state_reason = 'reactivated' where workspace_id = %s"
        " and role = 'tenant' and status = 'suspended' and state_reason = 'workspace_frozen'",
        [ws],
    )
    conn.execute(
        "insert into notifications (org_id, to_user_id, kind, template_vars)"
        " select %s, m.user_id, 'successor_effective', '{}'::jsonb from memberships m"
        " where m.workspace_id = %s and m.status = 'active'",
        [request["org_id"], ws],
    )
    lmqa_audit.append(
        conn,
        org_id=request["org_id"],
        workspace_id=ws,
        action="workspace.successor_effective",
        target_type="workspace",
        target_id=ws,
        payload={"request": str(request["id"])},
    )


def co_owner_set_effect(conn: Any, request: dict[str, Any]) -> None:
    conn.execute(
        "update memberships set co_owner = true where id = %s and role = 'super_admin'",
        [request["target_id"]],
    )


def freeze_workspace_cascade(conn: Any, workspace_id: str, reason: str = "workspace_frozen") -> int:
    """7.7: a frozen workspace suspends its active tenants with reason `workspace_frozen` and disables its codes;
    reactivation (`reactivate_workspace_cascade`) restores only those cascade-suspended tenants."""
    conn.execute(
        "update workspaces set status = 'frozen', frozen_at = now(), state_changed_at = now()"
        " where id = %s and status = 'active'",
        [workspace_id],
    )
    conn.execute(
        "update join_codes set state = 'disabled' where workspace_id = %s and state = 'active'",
        [workspace_id],
    )
    return conn.execute(
        "update memberships set status = 'suspended', state_reason = %s where workspace_id = %s"
        " and role = 'tenant' and status = 'active'",
        [reason, workspace_id],
    ).rowcount


def reactivate_workspace_cascade(conn: Any, workspace_id: str) -> int:
    conn.execute(
        "update workspaces set status = 'active', frozen_at = null, state_changed_at = now()"
        " where id = %s and status = 'frozen'",
        [workspace_id],
    )
    conn.execute(
        "update join_codes set state = 'active' where workspace_id = %s and state = 'disabled'"
        " and expires_at > now() and revoked_at is null",
        [workspace_id],
    )
    return conn.execute(
        "update memberships set status = 'active', state_reason = 'reactivated'"
        " where workspace_id = %s and role = 'tenant' and status = 'suspended'"
        " and state_reason = 'workspace_frozen'",
        [workspace_id],
    ).rowcount


def reconcile_auth0_roles(conn_factory: ConnFactory, auth0: Auth0Management) -> list[str]:
    """G2.11: detect role assignments made in Auth0 out of band. PostgreSQL is the authority; a difference raises
    an alert (and is never copied into the database)."""
    findings: list[str] = []
    with conn_factory() as conn:
        orgs = conn.execute(
            "select id, auth0_org_id from organizations where auth0_org_id is not null and status = 'active'"
        ).fetchall()
        for org in orgs:
            expected = {
                str(r["auth0_sub"]): str(r["role"])
                for r in conn.execute(
                    "select u.auth0_sub, m.role from memberships m join users u on u.id = m.user_id"
                    " where m.org_id = %s and m.status = 'active'",
                    [org["id"]],
                ).fetchall()
            }
            for sub in auth0.members(org["auth0_org_id"]):
                roles = auth0.member_roles(org["auth0_org_id"], sub)
                want = expected.get(sub)
                if want is None or roles not in ([want], []):
                    findings.append(f"{org['id']}:{sub}")
                    conn.execute(
                        "insert into alerts (org_id, rule, severity, summary, dedup_key)"
                        " values (%s, 'auth0_role_drift', 'page', 'Auth0 role assignment differs from PostgreSQL',"
                        " %s) on conflict do nothing",
                        [org["id"], f"auth0_role_drift:{org['id']}:{sub}"],
                    )
    return findings
