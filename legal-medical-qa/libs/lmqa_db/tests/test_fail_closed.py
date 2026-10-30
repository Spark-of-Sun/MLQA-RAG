"""G1.3: with no context every table returns zero rows, even on a reused pooled connection."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import text

from lmqa_db import (
    ContextRole,
    Database,
    DbContext,
    MissingContextError,
    SelfTestError,
    boot_self_test,
)
from lmqa_db.bootstrap import with_database
from lmqa_testing import world
from lmqa_testing.pg import fresh_database, role_dsn, superuser_dsn

if TYPE_CHECKING:
    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

READABLE = {
    "svc_ingestion": ("documents", "document_versions", "chunks", "doc_keys", "index_outbox"),
    "svc_retrieval": ("documents", "document_versions", "chunks", "retrieval_records"),
    "svc_generation": ("documents", "chunks", "retrieval_records"),
    "svc_validator": ("documents", "chunks", "retrieval_records"),
    "svc_identity": ("memberships", "workspaces", "join_codes", "matters", "matter_grants"),
}


async def _populate(stack: Stack) -> world.Workspace:
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, ws)
    matter = await world.create_matter(stack, ws)
    await world.grant(stack, ws, tenant, matter, 3)
    await world.add_document(
        stack, ws, ws.admin, ContextRole.ADMIN, visibility="matter", matter=matter
    )
    await world.add_document(stack, ws, tenant, ContextRole.TENANT, visibility="private")
    return ws


@pytest.mark.asyncio
async def test_unscoped_session_is_refused(stack: Stack) -> None:
    with pytest.raises(MissingContextError):
        async with stack.ingestion.scoped(None):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        DbContext(role=ContextRole.TENANT),
        DbContext(role=ContextRole.ADMIN, org_id=uuid4()),
        DbContext(role=ContextRole.TENANT, org_id=uuid4(), workspace_id=uuid4()),
        DbContext(role=ContextRole.SUPER_ADMIN),
    ],
)
async def test_incomplete_contexts_are_refused(stack: Stack, bad: DbContext) -> None:
    with pytest.raises(MissingContextError):
        async with stack.ingestion.scoped(bad):
            pass


@pytest.mark.asyncio
async def test_no_context_returns_zero_rows_while_a_context_returns_data(stack: Stack) -> None:
    ws = await _populate(stack)
    owner = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    for role, tables in READABLE.items():
        db: Database = getattr(stack, role.removeprefix("svc_"))
        for table in tables:
            query = text(f"SELECT count(*) FROM {table}")
            async with db.unscoped_for_self_test() as s:
                assert (await s.execute(query)).scalar_one() == 0, (role, table)
    # Proof the zero above is the policy at work and not an empty table:
    async with stack.ingestion.scoped(owner) as s:
        assert (await s.execute(text("SELECT count(*) FROM documents"))).scalar_one() >= 1


@pytest.mark.asyncio
async def test_empty_string_setting_on_a_reused_connection_does_not_raise_or_leak(
    migrated_db: str, stack: Stack
) -> None:
    """DEF-52: after a transaction-local set_config, the setting reads '' (not NULL) on reuse."""
    ws = await _populate(stack)
    async with await psycopg.AsyncConnection.connect(
        role_dsn("svc_ingestion", migrated_db)
    ) as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.org_id', %s, true), set_config('app.workspace_id', %s, true),"
                " set_config('app.user_id', %s, true), set_config('app.role', 'admin', true)",
                (str(ws.org), str(ws.id), str(ws.admin)),
            )
            cur = await conn.execute("SELECT count(*) FROM documents")
            seen = await cur.fetchone()
            assert seen is not None
            assert seen[0] >= 1
        # Same connection, new transaction, no context: the settings are now '' not NULL.
        async with conn.transaction():
            cur = await conn.execute("SELECT current_setting('app.org_id', true)")
            raw = await cur.fetchone()
            assert raw is not None
            assert raw[0] == "", "this is exactly the state DEF-52 describes"
            for table in READABLE["svc_ingestion"]:
                cur = await conn.execute(f"SELECT count(*) FROM {table}")  # type: ignore[arg-type]
                row = await cur.fetchone()
                assert row is not None
                assert row[0] == 0, table


@pytest.mark.asyncio
async def test_boot_self_test_passes_on_a_healthy_database(stack: Stack) -> None:
    other = DbContext(
        role=ContextRole.TENANT, org_id=uuid4(), workspace_id=uuid4(), user_id=uuid4()
    )
    await boot_self_test(stack.ingestion, readable_tables=READABLE["svc_ingestion"], other=other)
    await boot_self_test(stack.gateway, readable_tables=(), other=other)


@pytest.mark.asyncio
async def test_boot_self_test_refuses_to_start_when_force_rls_is_removed() -> None:
    name = "lmqa_selftest_broken"
    fresh_database(name)
    with psycopg.connect(with_database(superuser_dsn(), name), autocommit=True) as conn:
        conn.execute("ALTER TABLE documents NO FORCE ROW LEVEL SECURITY")
    db = Database(role_dsn("svc_ingestion", name), pooled=False, use_null_pool=True)
    other = DbContext(
        role=ContextRole.TENANT, org_id=uuid4(), workspace_id=uuid4(), user_id=uuid4()
    )
    try:
        with pytest.raises(SelfTestError, match="FORCE ROW LEVEL SECURITY"):
            await boot_self_test(db, readable_tables=("documents",), other=other)
    finally:
        await db.dispose()
