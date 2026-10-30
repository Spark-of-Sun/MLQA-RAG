"""G1.5: the Super Admin boundary holds in the database itself (doc 5.3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from lmqa_db import ContextRole, DbContext
from lmqa_testing import world

if TYPE_CHECKING:
    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

CONTENT_READERS = ("ingestion", "retrieval", "generation", "validator")
CONTENT_TABLES = ("documents", "document_versions", "chunks", "doc_keys")


async def _two_workspace_org(
    stack: Stack,
) -> tuple[world.Org, world.Workspace, world.Workspace, object]:
    org = await world.create_org(stack)
    a = await world.create_workspace(stack, org)
    b = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, a)
    matter = await world.create_matter(stack, a)
    await world.grant(stack, a, tenant, matter, 4)
    await world.add_document(
        stack, a, a.admin, ContextRole.ADMIN, visibility="matter", matter=matter, tier=4
    )
    await world.add_document(stack, a, tenant, ContextRole.TENANT, visibility="private")
    await world.add_document(stack, b, b.admin, ContextRole.ADMIN, visibility="private")
    await world.wall(stack, a, tenant, matter)
    return org, a, b, tenant


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", CONTENT_READERS)
async def test_super_admin_context_reads_no_content_through_any_content_role(
    stack: Stack, reader: str
) -> None:
    org, a, _b, _tenant = await _two_workspace_org(stack)
    super_admin = DbContext(
        role=ContextRole.SUPER_ADMIN, org_id=org.id, workspace_id=a.id, user_id=org.super_admin
    )
    db = getattr(stack, reader)
    for table in CONTENT_TABLES:
        async with db.scoped(super_admin) as s:
            rows = (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert rows == 0, (reader, table)
    # The same tables do hold data for a legitimate admin, so zero is the policy and not emptiness.
    admin = DbContext(role=ContextRole.ADMIN, org_id=org.id, workspace_id=a.id, user_id=a.admin)
    async with db.scoped(admin) as s:
        assert (await s.execute(text("SELECT count(*) FROM documents"))).scalar_one() >= 1


@pytest.mark.asyncio
async def test_super_admin_sees_admins_but_never_tenants_walls_or_matters(stack: Stack) -> None:
    org, _a, _b, tenant = await _two_workspace_org(stack)
    sa = DbContext(role=ContextRole.SUPER_ADMIN, org_id=org.id, user_id=org.super_admin)
    async with stack.identity.scoped(sa) as s:
        roles = (
            await s.execute(text("SELECT role, count(*) FROM memberships GROUP BY role"))
        ).all()
        by_role = {r[0]: r[1] for r in roles}
        assert by_role.get("admin") == 2
        assert by_role.get("super_admin") == 1
        assert "tenant" not in by_role, "tenant memberships are invisible to the Super Admin"
        for table in ("matter_walls", "matter_grants", "matters", "access_sessions"):
            count = (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table
        found = (
            await s.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": tenant}
            )
        ).scalar_one()
        assert found == 0


@pytest.mark.asyncio
async def test_super_admin_reads_workspace_usage_numbers_only(stack: Stack) -> None:
    org, a, b, _tenant = await _two_workspace_org(stack)
    async with stack.identity.scoped(world.SYSTEM) as s:
        for ws, tenants in ((a, 1), (b, 0)):
            await s.execute(
                text(
                    "INSERT INTO workspace_usage (workspace_id, org_id, tenant_count, document_count)"
                    " VALUES (:w, :o, :t, 3)"
                ),
                {"w": ws.id, "o": org.id, "t": tenants},
            )
    sa = DbContext(role=ContextRole.SUPER_ADMIN, org_id=org.id, user_id=org.super_admin)
    async with stack.identity.scoped(sa) as s:
        rows = (
            await s.execute(text("SELECT workspace_id, tenant_count FROM workspace_usage"))
        ).all()
        assert {r[0] for r in rows} == {a.id, b.id}
    # Super Admins may not write usage numbers: only the platform job does.
    async with stack.identity.scoped(sa) as s:
        result = await s.execute(text("UPDATE workspace_usage SET tenant_count = 99"))
        assert result.rowcount == 0, "RLS filters the UPDATE: no row is writable by a Super Admin"
    async with stack.identity.scoped(world.SYSTEM) as s:
        counts = (
            await s.execute(
                text("SELECT tenant_count FROM workspace_usage WHERE org_id = :o"), {"o": org.id}
            )
        ).all()
        assert 99 not in {c[0] for c in counts}
    with pytest.raises(Exception, match="row-level security"):
        async with stack.identity.scoped(sa) as s:
            await s.execute(
                text("INSERT INTO workspace_usage (workspace_id, org_id) VALUES (:w, :o)"),
                {"w": a.id, "o": org.id},
            )


@pytest.mark.asyncio
async def test_super_admin_sees_only_org_and_admin_audit_events_and_never_payloads(
    stack: Stack,
) -> None:
    org, a, _b, tenant = await _two_workspace_org(stack)
    system = DbContext(role=ContextRole.SYSTEM)
    async with stack.identity.scoped(system) as s:
        for chain, ws, scope, actor in (
            (f"org:{org.id}", None, "org", org.super_admin),
            (f"ws:{a.id}", a.id, "workspace", a.admin),
            (f"ws:{a.id}", a.id, "tenant", tenant),
        ):
            await s.execute(
                text(
                    "SELECT audit_append(:chain, :org, :ws, :actor, 'x', 'test.event', NULL, 'ok', NULL, NULL,"
                    " NULL, NULL, :scope, :payload, 'k1')"
                ),
                {
                    "chain": chain,
                    "org": org.id,
                    "ws": ws,
                    "actor": actor,
                    "scope": scope,
                    "payload": b"\x01\x02",
                },
            )
    sa = DbContext(role=ContextRole.SUPER_ADMIN, org_id=org.id, user_id=org.super_admin)
    async with stack.audit_reader.scoped(sa) as s:
        scopes = {r[0] for r in (await s.execute(text("SELECT scope FROM audit_event"))).all()}
        assert scopes <= {"org", "admin"}
        assert "org" in scopes
        assert (await s.execute(text("SELECT count(*) FROM audit_payload"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_super_admin_of_one_org_sees_nothing_of_another(stack: Stack) -> None:
    org1, _a1, _b1, _t1 = await _two_workspace_org(stack)
    org2, _a2, _b2, _t2 = await _two_workspace_org(stack)
    sa1 = DbContext(role=ContextRole.SUPER_ADMIN, org_id=org1.id, user_id=org1.super_admin)
    async with stack.identity.scoped(sa1) as s:
        foreign = (
            await s.execute(
                text("SELECT count(*) FROM memberships WHERE org_id = :o"), {"o": org2.id}
            )
        ).scalar_one()
        assert foreign == 0
        assert (
            await s.execute(text("SELECT count(*) FROM orgs WHERE id = :o"), {"o": org2.id})
        ).scalar_one() == 0
        assert (
            await s.execute(text("SELECT count(*) FROM orgs WHERE id = :o"), {"o": org1.id})
        ).scalar_one() == 1
