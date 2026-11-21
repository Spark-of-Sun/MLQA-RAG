"""Identity domain logic (doc 6, 7).

Onboarding, approvals, lifecycle cascades, grants, matters and walls.

Every read and write runs under the *acting* principal's database context. A Super Admin context
cannot see tenants, walls or matters even if this code asked, and a tenant context cannot approve
anyone; the policies and the state-machine triggers are the enforcement, the checks here only give
clean answers. Nobody approves or changes their own membership (also a CHECK constraint).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import text
from valkey.asyncio import Valkey

from identity.auth0 import Auth0Management
from identity.codes import CodeRejected, CodeService
from lmqa_audit import AuditEvent, AuditKeyManager, AuditWriter, month_start
from lmqa_db import ContextRole, Database, DbContext
from lmqa_keys import KeyProvider, KeyService
from lmqa_security.codes import CodeKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


INVALIDATIONS: Final = "principal-invalidations"
SYSTEM: Final = DbContext(role=ContextRole.SYSTEM)
ACTIONS: Final = {"approve", "reject", "suspend", "reactivate"}
POLICY_FIELDS: Final = {
    "join_policy",
    "default_visibility",
    "delivery_mode",
    "on_fail",
    "emergency_access",
}
RESULT_STATE: Final = {
    "approve": "active",
    "reject": "rejected",
    "suspend": "suspended",
    "reactivate": "active",
}


def _affected(result: Any) -> int:  # noqa: ANN401 - SQLAlchemy types rowcount only on CursorResult
    """Rows changed by a statement."""
    return int(result.rowcount)


class NotFoundError(LookupError):
    """Outside the caller's scope or absent: the same answer (404)."""


class ConflictError(RuntimeError):
    """The request conflicts with the current state."""


@dataclass(slots=True)
class Identity:
    """The identity service's domain object. All collaborators are real."""

    db: Database
    keys: KeyService
    provider: KeyProvider
    codes: CodeService
    valkey: Valkey
    auth0: Auth0Management | None = None
    audit: AuditWriter = field(default_factory=AuditWriter)
    auto_activate_orgs: bool = (
        True  # development default; production waits for operator approval (D9)
    )

    # ------------------------------------------------------------------ helpers
    async def _user(self, s: AsyncSession, sub: str) -> UUID:
        row = (
            await s.execute(text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": sub})
        ).scalar()
        if row is not None:
            return UUID(str(row))
        new = uuid.uuid7()
        await s.execute(
            text("INSERT INTO users (id, auth0_sub) VALUES (:i, :s)"), {"i": new, "s": sub}
        )
        return new

    async def _is_member(self, s: AsyncSession, user: UUID) -> bool:
        found = (
            await s.execute(text("SELECT 1 FROM memberships WHERE user_id = :u"), {"u": user})
        ).first()
        return found is not None

    async def _log(  # noqa: PLR0913, PLR0917 - an audit event genuinely has these fields
        self,
        s: AsyncSession,
        org: UUID,
        ws: UUID | None,
        action: str,
        actor: UUID | None,
        role: str,
        target: str | None = None,
        scope: str = "admin",
    ) -> None:
        event = AuditEvent(action, "ok", scope if ws is None else "workspace", actor, role, target)
        await self.audit.append(s, org, ws, event)

    async def _invalidate(self, user_ids: list[UUID]) -> None:
        """Delete the shared principal cache entries, then tell every gateway (doc 8.6)."""
        async with self.db.scoped(SYSTEM) as s:
            subs = (
                (
                    await s.execute(
                        text("SELECT auth0_sub FROM users WHERE id = ANY(:i)"), {"i": user_ids}
                    )
                )
                .scalars()
                .all()
            )
        for sub in subs:
            await self.valkey.delete(f"principal:{sub}")
        for uid in user_ids:  # gateways drop their in-process copies and cut open streams at once
            await self.valkey.publish(INVALIDATIONS, json.dumps({"user_id": str(uid)}))

    # ------------------------------------------------------------------ onboarding
    async def create_organization(
        self, sub: str, name: str, deployment: str, region: str = "us"
    ) -> dict[str, Any]:
        """Path A: create an organization and its Super Admin.

        Idempotent: a user has one membership.
        """
        async with self.db.scoped(SYSTEM) as s:
            user = await self._user(s, sub)
            existing = (
                await s.execute(
                    text("SELECT org_id FROM memberships WHERE user_id = :u"), {"u": user}
                )
            ).scalar()
            if existing:
                return {"organization_id": str(existing), "created": False}
            org = uuid.uuid7()
            await s.execute(
                text(
                    "INSERT INTO orgs (id, name, deployment_type, region) VALUES (:i, :n, :d, :r)"
                ),
                {"i": org, "n": name.strip()[:120], "d": deployment, "r": region},
            )
            ids = await self.keys.provision_org(org)  # org CMK and a separate escrow CMK
            await s.execute(
                text(
                    "INSERT INTO org_keys (org_id, kms_key_id, escrow_key_id) VALUES (:o, :k, :e)"
                ),
                {"o": org, "k": ids.cmk_id, "e": ids.escrow_id},
            )
            await s.execute(
                text(
                    "INSERT INTO memberships (user_id, org_id, role, state) VALUES (:u, :o, "
                    "'super_admin', 'active')"
                ),
                {"u": user, "o": org},
            )
            if self.auth0 is not None:
                auth0_org = await self.auth0.create_organization(
                    f"org-{org.hex[:12]}", name.strip()[:120]
                )
                await s.execute(
                    text("UPDATE orgs SET auth0_org_id = :a WHERE id = :o"),
                    {"a": auth0_org, "o": org},
                )
                await self.auth0.add_member(auth0_org, sub)
                await self.auth0.mark_privileged(sub)
            if self.auto_activate_orgs:
                await s.execute(text("UPDATE orgs SET state = 'active' WHERE id = :o"), {"o": org})
            await self._log(
                s, org, None, "organization.created", user, "super_admin", f"org:{org}", "org"
            )
        state = "active" if self.auto_activate_orgs else "pending"
        return {"organization_id": str(org), "created": True, "state": state}

    async def join_admin(self, sub: str, raw_code: str, ip: str | None) -> dict[str, str]:
        """Path B: an Organization Code creates a pending admin and a pending workspace."""
        code = await self.codes.verify(CodeKind.ORGANIZATION, raw_code, sub, ip)
        async with self.db.scoped(SYSTEM) as s:
            user = await self._user(s, sub)
            if await self._is_member(s, user):
                raise CodeRejected  # an existing member learns nothing about the code
            org_state = (
                await s.execute(text("SELECT state FROM orgs WHERE id = :o"), {"o": code.org_id})
            ).scalar()
            if org_state != "active":
                raise CodeRejected
            ws = uuid.uuid7()
            await s.execute(
                text("INSERT INTO workspaces (id, org_id, admin_user_id) VALUES (:w, :o, :u)"),
                {"w": ws, "o": code.org_id, "u": user},
            )
            await s.execute(
                text(
                    "INSERT INTO memberships (user_id, org_id, workspace_id, role) VALUES (:u, :o, "
                    ":w, 'admin')"
                ),
                {"u": user, "o": code.org_id, "w": ws},
            )
            await CodeService.consume(s, code)
            await self._log(
                s,
                code.org_id,
                None,
                "admin.join_requested",
                user,
                "admin",
                f"workspace:{ws}",
                "org",
            )
        return {"state": "pending_approval"}

    async def preview_tenant_code(self, sub: str, raw_code: str, ip: str | None) -> dict[str, Any]:
        """Validate an Admin Code WITHOUT consuming a use.

        Any invalid code gives the uniform rejection.
        """
        code = await self.codes.verify(CodeKind.ADMIN, raw_code, sub, ip)
        return {"valid": True, "workspace_label": f"Workspace {str(code.workspace_id)[:8]}"}

    async def join_tenant(self, sub: str, raw_code: str, ip: str | None) -> dict[str, str]:
        """Path C: an Admin Code creates a pending (or, with policy ``auto``.

        Active) tenant membership.
        """
        code = await self.codes.verify(CodeKind.ADMIN, raw_code, sub, ip)
        async with self.db.scoped(SYSTEM) as s:
            user = await self._user(s, sub)
            if await self._is_member(s, user):
                raise CodeRejected
            ws = (
                await s.execute(
                    text("SELECT state, join_policy, admin_user_id FROM workspaces WHERE id = :w"),
                    {"w": code.workspace_id},
                )
            ).one()
            if ws[0] != "active":
                raise CodeRejected
            await s.execute(
                text(
                    "INSERT INTO memberships (user_id, org_id, workspace_id, role) VALUES (:u, :o, "
                    ":w, 'tenant')"
                ),
                {"u": user, "o": code.org_id, "w": code.workspace_id},
            )
            state = "pending_approval"
            if (
                ws[1] == "auto"
            ):  # domain_allowlist needs verified email domains: treated as manual in the MVP
                await s.execute(
                    text(
                        "UPDATE memberships SET state = 'active', approved_by = :a WHERE user_id = "
                        ":u"
                    ),
                    {"a": ws[2], "u": user},
                )
                state = "active"
            await CodeService.consume(s, code)
            await self._log(
                s,
                code.org_id,
                code.workspace_id,
                "tenant.join_requested",
                user,
                "tenant",
                f"user:{user}",
            )
        return {"state": state}

    async def status(self, sub: str) -> dict[str, Any]:
        """The caller's membership state and Auth0 organization (pending page, re-login)."""
        async with self.db.scoped(SYSTEM) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT m.role, m.state, m.state_reason, o.auth0_org_id FROM memberships m "
                        "JOIN users u ON u.id = m.user_id JOIN orgs o ON o.id = m.org_id "
                        "WHERE u.auth0_sub = :s"
                    ),
                    {"s": sub},
                )
            ).first()
        if row is None:
            return {"member": False}
        return {
            "member": True,
            "role": row[0],
            "state": row[1],
            "reason": row[2],
            "auth0_org_id": row[3],
        }

    async def me(self, ctx: DbContext) -> dict[str, Any]:
        """The caller's principal summary and capabilities (never from the token's role claim)."""
        async with self.db.scoped(ctx) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT m.role, m.state, o.state, m.workspace_id FROM memberships m"
                        " JOIN orgs o ON o.id = m.org_id WHERE m.user_id = :u"
                    ),
                    {"u": ctx.user},
                )
            ).first()
        if row is None:
            raise NotFoundError
        role, mstate, ostate, ws = row
        caps: list[str] = ["status"]
        if ostate == "active" and mstate == "active":
            caps = {
                "super_admin": ["manage_admins", "org_code", "org_audit"],
                "admin": ["chat", "library", "manage_tenants", "walls", "workspace_audit"],
                "tenant": ["chat", "library", "own_audit"],
            }[role]
        return {
            "user_id": str(ctx.user),
            "role": role,
            "state": mstate,
            "org_state": ostate,
            "workspace_id": str(ws) if ws else None,
            "capabilities": caps,
        }

    # ------------------------------------------------------------------ codes
    async def generate_org_code(self, ctx: DbContext) -> str:
        """Super Admin: (re)generate the Organization Code. Shown once, rotating any active one."""
        async with self.db.scoped(ctx) as s:
            state = (
                await s.execute(text("SELECT state FROM orgs WHERE id = :o"), {"o": ctx.org})
            ).scalar()
            if state != "active":
                msg = "the organization is not active"
                raise ConflictError(msg)
            display = await self.codes.create(s, CodeKind.ORGANIZATION, ctx.org, None, ctx.user)
            await self._log(
                s, ctx.org, None, "org_code.generated", ctx.user, "super_admin", None, "org"
            )
        return display

    async def generate_admin_code(self, ctx: DbContext) -> str:
        """Admin: (re)generate the Admin Code of their own workspace."""
        async with self.db.scoped(ctx) as s:
            state = (
                await s.execute(text("SELECT state FROM workspaces WHERE id = :w"), {"w": ctx.ws})
            ).scalar()
            if state != "active":
                msg = "the workspace is not active"
                raise ConflictError(msg)
            display = await self.codes.create(s, CodeKind.ADMIN, ctx.org, ctx.ws, ctx.user)
            await self._log(s, ctx.org, ctx.ws, "admin_code.generated", ctx.user, "admin")
        return display

    # ------------------------------------------------------------------ Super Admin: admins
    async def list_admins(self, ctx: DbContext) -> list[dict[str, Any]]:
        """Admins of the organization with workspace state and usage numbers (never tenants)."""
        async with self.db.scoped(ctx) as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT m.user_id, m.state, m.state_reason, m.created_at, w.id, w.state,"
                        " coalesce(u.tenant_count, 0), coalesce(u.document_count, 0) FROM "
                        "memberships m"
                        " JOIN workspaces w ON w.id = m.workspace_id"
                        " LEFT JOIN workspace_usage u ON u.workspace_id = w.id"
                        " WHERE m.role = 'admin' ORDER BY m.created_at"
                    )
                )
            ).all()
        return [
            {
                "user_id": str(r[0]),
                "state": r[1],
                "reason": r[2],
                "requested_at": r[3].isoformat(),
                "workspace_id": str(r[4]),
                "workspace_state": r[5],
                "tenant_count": r[6],
                "document_count": r[7],
            }
            for r in rows
        ]

    async def decide_admin(self, ctx: DbContext, admin_id: UUID, action: str) -> dict[str, str]:  # noqa: C901
        """Approve, reject, suspend or reactivate an admin."""
        if action not in ACTIONS or ctx.role is not ContextRole.SUPER_ADMIN:
            raise NotFoundError  # only a Super Admin decides admins; anyone else gets the same 404
        if admin_id == ctx.user:
            msg = "nobody changes their own membership"
            raise ConflictError(msg)
        async with self.db.scoped(
            ctx
        ) as s:  # RLS: a Super Admin sees only admins of their own organization
            row = (
                await s.execute(
                    text(
                        "SELECT state, workspace_id FROM memberships WHERE user_id = :u AND role = "
                        "'admin'"
                    ),
                    {"u": admin_id},
                )
            ).first()
        if row is None:
            raise NotFoundError
        state, ws = row
        async with self.db.scoped(SYSTEM) as s:  # lifecycle steps need workspace and key tables
            org_auth0 = (
                await s.execute(text("SELECT auth0_org_id FROM orgs WHERE id = :o"), {"o": ctx.org})
            ).scalar()
            sub = (
                await s.execute(text("SELECT auth0_sub FROM users WHERE id = :u"), {"u": admin_id})
            ).scalar()
            affected = [admin_id]
            if action == "approve" and state == "pending_approval":
                await self._provision_workspace(s, ctx, ws)
                await s.execute(
                    text(
                        "UPDATE memberships SET state = 'active', approved_by = :a WHERE user_id = "
                        ":u"
                    ),
                    {"a": ctx.user, "u": admin_id},
                )
            elif action == "reject" and state == "pending_approval":
                await s.execute(
                    text("UPDATE memberships SET state = 'rejected' WHERE user_id = :u"),
                    {"u": admin_id},
                )
                await s.execute(
                    text(
                        "UPDATE workspaces SET state = 'rejected' WHERE id = :w AND state = "
                        "'pending'"
                    ),
                    {"w": ws},
                )
            elif action == "suspend" and state == "active":
                affected += await self._freeze(s, admin_id, ws)
            elif action == "reactivate" and state == "suspended":
                affected += await self._thaw(s, admin_id, ws)
            else:
                msg = f"cannot {action} an admin who is {state}"
                raise ConflictError(msg)
            await self._log(
                s,
                ctx.org,
                None,
                f"admin.{action}",
                ctx.user,
                "super_admin",
                f"user:{admin_id}",
                "admin",
            )
        await self._invalidate(affected)
        if self.auth0 is not None and org_auth0 and sub:
            if action == "approve":
                await self.auth0.add_member(org_auth0, sub)
                await self.auth0.mark_privileged(sub)
            elif action in {"suspend", "reject"}:
                await self.auth0.revoke_access(org_auth0, sub)
        return {"state": RESULT_STATE[action]}

    async def _provision_workspace(self, s: AsyncSession, ctx: DbContext, ws: UUID) -> None:
        """Pending -> provisioning -> active: workspace key, audit month key, usage row.

        Idempotent.
        """
        await s.execute(
            text(
                "UPDATE workspaces SET state = 'provisioning' WHERE id = :w AND state = 'pending'"
            ),
            {"w": ws},
        )
        cmk = (
            await s.execute(
                text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": ctx.org}
            )
        ).scalar_one()
        have = (
            await s.execute(text("SELECT 1 FROM workspace_keys WHERE workspace_id = :w"), {"w": ws})
        ).first()
        if not have:
            _key, wrapped = await self.keys.new_workspace_key(str(cmk), ctx.org, ws, 1)
            await s.execute(
                text(
                    "INSERT INTO workspace_keys (org_id, workspace_id, version, wrapped_key) "
                    "VALUES (:o, :w, 1, :k)"
                ),
                {"o": ctx.org, "w": ws, "k": wrapped},
            )
        await AuditKeyManager().ensure_month_key(
            s, self.provider, str(cmk), ctx.org, ws, month_start()
        )
        await s.execute(
            text(
                "INSERT INTO workspace_usage (workspace_id, org_id) VALUES (:w, :o) ON CONFLICT DO "
                "NOTHING"
            ),
            {"w": ws, "o": ctx.org},
        )
        await s.execute(
            text("UPDATE workspaces SET state = 'active' WHERE id = :w AND state = 'provisioning'"),
            {"w": ws},
        )

    @staticmethod
    async def _freeze(s: AsyncSession, admin: UUID, ws: UUID) -> list[UUID]:
        """Suspend an admin: workspace frozen, tenants suspended with ``workspace_frozen``.

        Codes disabled.
        """
        await s.execute(
            text(
                "UPDATE memberships SET state = 'suspended', state_reason = 'admin_action' WHERE "
                "user_id = :u"
            ),
            {"u": admin},
        )
        await s.execute(
            text("UPDATE workspaces SET state = 'frozen' WHERE id = :w AND state = 'active'"),
            {"w": ws},
        )
        tenants = (
            await s.execute(
                text(
                    "UPDATE memberships SET state = 'suspended', state_reason = 'workspace_frozen'"
                    " WHERE workspace_id = :w AND role = 'tenant' AND state = 'active' RETURNING "
                    "user_id"
                ),
                {"w": ws},
            )
        ).all()
        await s.execute(
            text(
                "UPDATE join_codes SET state = 'disabled' WHERE workspace_id = :w AND state = "
                "'active'"
            ),
            {"w": ws},
        )
        return [UUID(str(t[0])) for t in tenants]

    @staticmethod
    async def _thaw(s: AsyncSession, admin: UUID, ws: UUID) -> list[UUID]:
        """Reactivate: restore ONLY the tenants this cascade suspended.

        The Admin Code stays disabled until rotated.
        """
        await s.execute(
            text("UPDATE memberships SET state = 'active', state_reason = NULL WHERE user_id = :u"),
            {"u": admin},
        )
        await s.execute(
            text("UPDATE workspaces SET state = 'active' WHERE id = :w AND state = 'frozen'"),
            {"w": ws},
        )
        tenants = (
            await s.execute(
                text(
                    "UPDATE memberships SET state = 'active', state_reason = NULL WHERE "
                    "workspace_id = :w"
                    " AND role = 'tenant' AND state = 'suspended' AND state_reason = "
                    "'workspace_frozen'"
                    " RETURNING user_id"
                ),
                {"w": ws},
            )
        ).all()
        return [UUID(str(t[0])) for t in tenants]

    # Admin: tenants, grants, matters, walls, policy
    async def list_tenants(self, ctx: DbContext) -> list[dict[str, Any]]:
        """Tenants of the admin's own workspace."""
        async with self.db.scoped(ctx) as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT user_id, state, state_reason, created_at FROM memberships"
                        " WHERE role = 'tenant' ORDER BY created_at"
                    )
                )
            ).all()
        return [
            {"user_id": str(r[0]), "state": r[1], "reason": r[2], "requested_at": r[3].isoformat()}
            for r in rows
        ]

    async def decide_tenant(
        self,
        ctx: DbContext,
        tenant_id: UUID,
        action: str,
        grants: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Approve (optionally with grants), reject.

        Suspend or reactivate a tenant of this workspace.
        """
        if action not in ACTIONS or ctx.role is not ContextRole.ADMIN:
            raise NotFoundError  # only the workspace admin decides tenants
        source, target = {
            "approve": ("pending_approval", "active"),
            "reject": ("pending_approval", "rejected"),
            "suspend": ("active", "suspended"),
            "reactivate": ("suspended", "active"),
        }[action]
        async with self.db.scoped(ctx) as s:
            changed = await s.execute(
                text(
                    "UPDATE memberships SET state = :t, state_reason = :r,"
                    " approved_by = CASE WHEN :a THEN :ad ELSE approved_by END"
                    " WHERE user_id = :u AND role = 'tenant' AND state = :f"
                ),
                {
                    "t": target,
                    "f": source,
                    "u": tenant_id,
                    "a": action == "approve",
                    "ad": ctx.user,
                    "r": "admin_action" if action == "suspend" else None,
                },
            )
            if _affected(changed) == 0:
                exists = (
                    await s.execute(
                        text("SELECT 1 FROM memberships WHERE user_id = :u AND role = 'tenant'"),
                        {"u": tenant_id},
                    )
                ).first()
                if exists is None:
                    raise NotFoundError
                msg = f"cannot {action} this tenant in its current state"
                raise ConflictError(msg)
            if action == "approve" and grants:
                await self._put_grants(s, ctx, tenant_id, grants)
            await self._log(
                s, ctx.org, ctx.ws, f"tenant.{action}", ctx.user, "admin", f"user:{tenant_id}"
            )
        await self._invalidate([tenant_id])
        return {"state": target}

    @staticmethod
    async def _put_grants(
        s: AsyncSession, ctx: DbContext, tenant: UUID, grants: list[dict[str, Any]]
    ) -> None:
        await s.execute(text("DELETE FROM matter_grants WHERE user_id = :u"), {"u": tenant})
        for g in grants:
            await s.execute(
                text(
                    "INSERT INTO matter_grants (org_id, workspace_id, matter_id, user_id, "
                    "max_tier, granted_by,"
                    " expires_at) VALUES (:o, :w, :m, :u, :t, :a, :e)"
                ),
                {
                    "o": ctx.org,
                    "w": ctx.ws,
                    "m": UUID(str(g["matter_id"])),
                    "u": tenant,
                    "t": int(g["max_tier"]),
                    "a": ctx.user,
                    "e": g.get("expires_at"),
                },
            )

    async def set_grants(
        self, ctx: DbContext, tenant_id: UUID, grants: list[dict[str, Any]]
    ) -> None:
        """Replace a tenant's grants (matter + tier ceiling + optional expiry).

        Applies on the next request.
        """
        async with self.db.scoped(ctx) as s:
            found = (
                await s.execute(
                    text("SELECT 1 FROM memberships WHERE user_id = :u AND role = 'tenant'"),
                    {"u": tenant_id},
                )
            ).first()
            if found is None:
                raise NotFoundError
            await self._put_grants(s, ctx, tenant_id, grants)
            await self._log(
                s, ctx.org, ctx.ws, "grants.set", ctx.user, "admin", f"user:{tenant_id}"
            )
        await self._invalidate([tenant_id])

    async def list_matters(self, ctx: DbContext) -> list[dict[str, Any]]:
        """Matters the caller may see (an admin: all; a tenant: only granted ones)."""
        async with self.db.scoped(ctx) as s:
            rows = (
                await s.execute(text("SELECT id, label, type FROM matters ORDER BY created_at"))
            ).all()
        return [{"id": str(r[0]), "label": r[1], "type": r[2]} for r in rows]

    async def create_matter(
        self, ctx: DbContext, label: str, kind: str = "matter"
    ) -> dict[str, str]:
        """Create a matter or patient scope."""
        mid = uuid.uuid7()
        async with self.db.scoped(ctx) as s:
            await s.execute(
                text(
                    "INSERT INTO matters (id, org_id, workspace_id, label, type) VALUES (:i, :o, "
                    ":w, :l, :t)"
                ),
                {"i": mid, "o": ctx.org, "w": ctx.ws, "l": label.strip()[:200], "t": kind},
            )
            await self._log(
                s, ctx.org, ctx.ws, "matter.created", ctx.user, "admin", f"matter:{mid}"
            )
        return {"id": str(mid)}

    async def rename_matter(self, ctx: DbContext, matter_id: UUID, label: str) -> None:
        """Change a matter's label."""
        async with self.db.scoped(ctx) as s:
            changed = await s.execute(
                text("UPDATE matters SET label = :l WHERE id = :i"),
                {"l": label.strip()[:200], "i": matter_id},
            )
            if _affected(changed) == 0:
                raise NotFoundError

    async def delete_matter(self, ctx: DbContext, matter_id: UUID) -> None:
        """Delete an unused matter (grants or walls still pointing at it are a conflict)."""
        async with self.db.scoped(ctx) as s:
            in_use = (
                await s.execute(
                    text(
                        "SELECT 1 FROM matter_grants WHERE matter_id = :m UNION ALL"
                        " SELECT 1 FROM matter_walls WHERE matter_id = :m"
                    ),
                    {"m": matter_id},
                )
            ).first()
            if in_use:
                msg = "the matter still has grants or walls"
                raise ConflictError(msg)
            gone = await s.execute(text("DELETE FROM matters WHERE id = :i"), {"i": matter_id})
            if _affected(gone) == 0:
                raise NotFoundError

    async def create_wall(
        self, ctx: DbContext, user_id: UUID, matter_id: UUID, reason_code: str
    ) -> None:
        """Create an ethical wall.

        One admin, instant, effective on the next request (lifting is governance).
        """
        async with self.db.scoped(ctx) as s:
            await s.execute(
                text(
                    "INSERT INTO matter_walls (org_id, workspace_id, matter_id, user_id, "
                    "reason_code, created_by)"
                    " VALUES (:o, :w, :m, :u, :r, :a) ON CONFLICT DO NOTHING"
                ),
                {
                    "o": ctx.org,
                    "w": ctx.ws,
                    "m": matter_id,
                    "u": user_id,
                    "r": reason_code[:60],
                    "a": ctx.user,
                },
            )
            await self._log(
                s, ctx.org, ctx.ws, "wall.created", ctx.user, "admin", f"user:{user_id}"
            )
        await self._invalidate([user_id])

    async def list_walls(self, ctx: DbContext) -> list[dict[str, str]]:
        """Walls of this workspace (readable only by its admin)."""
        async with self.db.scoped(ctx) as s:
            rows = (
                await s.execute(
                    text("SELECT user_id, matter_id, reason_code, effective_from FROM matter_walls")
                )
            ).all()
        return [
            {
                "user_id": str(r[0]),
                "matter_id": str(r[1]),
                "reason": r[2],
                "since": r[3].isoformat(),
            }
            for r in rows
        ]

    async def get_policy(self, ctx: DbContext) -> dict[str, Any]:
        """The workspace policy."""
        async with self.db.scoped(ctx) as s:
            r = (
                await s.execute(
                    text(
                        "SELECT join_policy, default_visibility, delivery_mode, on_fail, "
                        "emergency_access,"
                        " admin_can_read_private FROM workspaces WHERE id = :w"
                    ),
                    {"w": ctx.ws},
                )
            ).one()
        names = (
            "join_policy",
            "default_visibility",
            "delivery_mode",
            "on_fail",
            "emergency_access",
            "admin_can_read_private",
        )
        return dict(zip(names, r, strict=True))

    async def patch_policy(self, ctx: DbContext, changes: dict[str, Any]) -> dict[str, Any]:
        """Change allowed policy fields.

        ``admin_can_read_private`` is a governance request and is refused here.
        """
        if set(changes) - POLICY_FIELDS:
            msg = "only " + ", ".join(sorted(POLICY_FIELDS)) + " can be changed here"
            raise ConflictError(msg)
        async with self.db.scoped(ctx) as s:
            for key, value in changes.items():  # key is allow-listed above
                await s.execute(
                    text(f"UPDATE workspaces SET {key} = :v WHERE id = :w"),  # noqa: S608 - key is allow-listed in POLICY_FIELDS
                    {"v": value, "w": ctx.ws},
                )
            await self._log(s, ctx.org, ctx.ws, "workspace.policy_changed", ctx.user, "admin")
        return await self.get_policy(ctx)
