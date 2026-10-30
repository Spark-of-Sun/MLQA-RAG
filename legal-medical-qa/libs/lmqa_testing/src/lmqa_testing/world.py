"""Build real organizations, workspaces, members and documents through the service roles.

Everything here goes through the same database roles and policies the services use (doc 19.1,
R5): identity creates control-plane rows in ``system`` context, ingestion creates documents in
the owner's context. Document and chunk ``*_ciphertext`` columns hold random bytes: they are
opaque ciphertext by definition, not document text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import text

from lmqa_db import ContextRole, DbContext

if TYPE_CHECKING:
    from datetime import datetime

    from lmqa_testing.fixtures import Stack

SYSTEM = DbContext(role=ContextRole.SYSTEM)


@dataclass(frozen=True, slots=True)
class Org:
    """An organization with its Super Admin."""

    id: UUID
    super_admin: UUID


@dataclass(frozen=True, slots=True)
class Workspace:
    """A workspace with its admin."""

    org: UUID
    id: UUID
    admin: UUID


def ctx(
    role: ContextRole, org: UUID, ws: UUID | None = None, user: UUID | None = None
) -> DbContext:
    """Shorthand for a request context."""
    return DbContext(role=role, org_id=org, workspace_id=ws, user_id=user)


async def create_user(stack: Stack) -> UUID:
    """Insert an identity row (the Auth0 subject is unique per user)."""
    uid = uuid4()
    async with stack.identity.scoped(SYSTEM) as s:
        await s.execute(
            text("INSERT INTO users (id, auth0_sub) VALUES (:id, :sub)"),
            {"id": uid, "sub": f"auth0|{uid.hex}"},
        )
    return uid


async def create_org(stack: Stack, deployment: str = "legal") -> Org:
    """Create an active organization and its Super Admin through the legal transitions."""
    org_id = uuid4()
    sa = await create_user(stack)
    async with stack.identity.scoped(SYSTEM) as s:
        await s.execute(
            text("INSERT INTO orgs (id, name, deployment_type) VALUES (:id, :n, :d)"),
            {"id": org_id, "n": f"org-{org_id.hex[:8]}", "d": deployment},
        )
        await s.execute(text("UPDATE orgs SET state = 'active' WHERE id = :id"), {"id": org_id})
        await s.execute(
            text(
                "INSERT INTO memberships (user_id, org_id, role, state)"
                " VALUES (:u, :o, 'super_admin', 'active')"
            ),
            {"u": sa, "o": org_id},
        )
    return Org(id=org_id, super_admin=sa)


async def create_workspace(stack: Stack, org: Org) -> Workspace:
    """Create an active workspace and an active admin (approved by the Super Admin)."""
    ws_id = uuid4()
    admin = await create_user(stack)
    async with stack.identity.scoped(SYSTEM) as s:
        await s.execute(
            text("INSERT INTO workspaces (id, org_id, admin_user_id) VALUES (:w, :o, :a)"),
            {"w": ws_id, "o": org.id, "a": admin},
        )
        await s.execute(
            text(
                "INSERT INTO memberships (user_id, org_id, workspace_id, role)"
                " VALUES (:u, :o, :w, 'admin')"
            ),
            {"u": admin, "o": org.id, "w": ws_id},
        )
        for state in ("provisioning", "active"):
            await s.execute(
                text("UPDATE workspaces SET state = :s WHERE id = :w"), {"s": state, "w": ws_id}
            )
        await s.execute(
            text("UPDATE memberships SET state = 'active', approved_by = :sa WHERE user_id = :u"),
            {"sa": org.super_admin, "u": admin},
        )
    return Workspace(org=org.id, id=ws_id, admin=admin)


async def create_tenant(stack: Stack, ws: Workspace) -> UUID:
    """Create an active tenant approved by the workspace admin."""
    tenant = await create_user(stack)
    async with stack.identity.scoped(ctx(ContextRole.SYSTEM, ws.org)) as s:
        await s.execute(
            text(
                "INSERT INTO memberships (user_id, org_id, workspace_id, role)"
                " VALUES (:u, :o, :w, 'tenant')"
            ),
            {"u": tenant, "o": ws.org, "w": ws.id},
        )
        await s.execute(
            text("UPDATE memberships SET state = 'active', approved_by = :a WHERE user_id = :u"),
            {"a": ws.admin, "u": tenant},
        )
    return tenant


async def create_matter(stack: Stack, ws: Workspace, label: str = "matter") -> UUID:
    """Create a matter as the workspace admin."""
    matter = uuid4()
    async with stack.identity.scoped(ctx(ContextRole.ADMIN, ws.org, ws.id, ws.admin)) as s:
        await s.execute(
            text("INSERT INTO matters (id, org_id, workspace_id, label) VALUES (:m, :o, :w, :l)"),
            {"m": matter, "o": ws.org, "w": ws.id, "l": f"{label}-{matter.hex[:6]}"},
        )
    return matter


async def grant(
    stack: Stack,
    ws: Workspace,
    tenant: UUID,
    matter: UUID,
    max_tier: int,
    expires: datetime | None = None,
) -> None:
    """Grant a tenant a matter with a tier ceiling, as the workspace admin."""
    async with stack.identity.scoped(ctx(ContextRole.ADMIN, ws.org, ws.id, ws.admin)) as s:
        await s.execute(
            text(
                "INSERT INTO matter_grants (org_id, workspace_id, matter_id, user_id, max_tier, granted_by, expires_at)"
                " VALUES (:o, :w, :m, :u, :t, :a, :e)"
            ),
            {
                "o": ws.org,
                "w": ws.id,
                "m": matter,
                "u": tenant,
                "t": max_tier,
                "a": ws.admin,
                "e": expires,
            },
        )


async def wall(stack: Stack, ws: Workspace, user: UUID, matter: UUID) -> None:
    """Create an ethical wall as the workspace admin."""
    async with stack.identity.scoped(ctx(ContextRole.ADMIN, ws.org, ws.id, ws.admin)) as s:
        await s.execute(
            text(
                "INSERT INTO matter_walls (org_id, workspace_id, matter_id, user_id, reason_code, created_by)"
                " VALUES (:o, :w, :m, :u, 'conflict', :a)"
            ),
            {"o": ws.org, "w": ws.id, "m": matter, "u": user, "a": ws.admin},
        )


async def add_document(
    stack: Stack,
    ws: Workspace,
    owner: UUID,
    role: ContextRole,
    *,
    visibility: str,
    tier: int = 1,
    matter: UUID | None = None,
    chunks: int = 1,
) -> UUID:
    """Create an indexed document with chunks as ``svc_ingestion`` in the owner's context."""
    doc = uuid4()
    owner_ctx = ctx(role, ws.org, ws.id, owner)
    async with stack.ingestion.scoped(owner_ctx) as s:
        await s.execute(
            text(
                "INSERT INTO documents (id, org_id, workspace_id, owner_user_id, matter_id,"
                " title_ciphertext, visibility, confidentiality_tier)"
                " VALUES (:d, :o, :w, :u, :m, :t, :v, :tier)"
            ),
            {
                "d": doc,
                "o": ws.org,
                "w": ws.id,
                "u": owner,
                "m": matter,
                "t": os.urandom(32),
                "v": visibility,
                "tier": tier,
            },
        )
        for ordinal in range(chunks):
            await s.execute(
                text(
                    "INSERT INTO chunks (org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id,"
                    " matter_id, visibility, confidentiality_tier, kind, page_start, page_end,"
                    " text_ciphertext, text_sha256, token_count)"
                    " VALUES (:o, :w, :d, 1, :n, :u, :m, :v, :tier, 'paragraph', 1, 1, :c, :h, 50)"
                ),
                {
                    "o": ws.org,
                    "w": ws.id,
                    "d": doc,
                    "n": ordinal,
                    "u": owner,
                    "m": matter,
                    "v": visibility,
                    "tier": tier,
                    "c": os.urandom(64),
                    "h": os.urandom(32).hex(),
                },
            )
        for status in ("scanning", "parsing", "indexing", "indexed"):
            await s.execute(
                text("UPDATE documents SET status = :s WHERE id = :d"), {"s": status, "d": doc}
            )
    return doc
