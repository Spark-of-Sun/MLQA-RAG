"""Live integration tests verifying PostgreSQL RLS enforcement via PgBouncer."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from lmqa_db import TenantContext, build_set_local_statements


@pytest.mark.stage0
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_pgbouncer_rls_tenant_isolation() -> None:
    """Verify non-superuser service role cannot read data across tenant boundaries."""
    # Connect as admin to insert test row
    admin_conn = await asyncpg.connect(
        "postgresql://lmqa_admin:lmqa_secret@localhost:5432/lmqa", timeout=5
    )
    try:
        tenant_1 = uuid.uuid4()
        tenant_2 = uuid.uuid4()
        await admin_conn.execute(
            "INSERT INTO orgs (id, name) VALUES ($1, $2)", tenant_1, "Tenant 1 Legal Corp"
        )
    finally:
        await admin_conn.close()

    try:
        # Connect through PgBouncer as non-superuser lmqa_ops role
        service_conn = await asyncpg.connect(
            "postgresql://lmqa_ops:secret@localhost:6432/lmqa", timeout=5
        )
        try:
            tr = service_conn.transaction()
            await tr.start()

            # Query under tenant 1 context
            ctx1 = TenantContext(org_id=tenant_1)
            for stmt in build_set_local_statements(ctx1):
                await service_conn.execute(stmt)
            rows_1 = await service_conn.fetch("SELECT id, name FROM orgs")
            assert len(rows_1) == 1
            assert rows_1[0]["name"] == "Tenant 1 Legal Corp"

            # Query under tenant 2 context: must return 0 rows (RLS barrier)
            ctx2 = TenantContext(org_id=tenant_2)
            for stmt in build_set_local_statements(ctx2):
                await service_conn.execute(stmt)
            rows_2 = await service_conn.fetch("SELECT id, name FROM orgs")
            assert len(rows_2) == 0

            await tr.rollback()
        finally:
            await service_conn.close()
    finally:
        # Clean up
        clean_conn = await asyncpg.connect(
            "postgresql://lmqa_admin:lmqa_secret@localhost:5432/lmqa", timeout=5
        )
        try:
            await clean_conn.execute("DELETE FROM orgs WHERE id = $1", tenant_1)
        finally:
            await clean_conn.close()
