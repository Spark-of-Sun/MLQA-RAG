"""G1.7: transaction-pooling safety on the real PgBouncer (doc 10.3, DEF-52, DEF-53)."""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from typing import TYPE_CHECKING

import psycopg
import pytest
from sqlalchemy import text

from lmqa_db import ContextRole, Database, DbContext
from lmqa_db.bootstrap import repo_root
from lmqa_db.sqlscan import scan_repository, scan_text
from lmqa_testing import world
from lmqa_testing.pg import pooled_role_dsn

if TYPE_CHECKING:
    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]
TRANSACTIONS = 10_000
CONCURRENCY = 200


async def _principals(stack: Stack) -> list[tuple[DbContext, int]]:
    """Two organizations; every user owns three private documents (so each sees exactly three)."""
    out: list[tuple[DbContext, int]] = []
    for _ in range(2):
        org = await world.create_org(stack)
        ws = await world.create_workspace(stack, org)
        users = [(ws.admin, ContextRole.ADMIN)]
        users += [(await world.create_tenant(stack, ws), ContextRole.TENANT) for _ in range(3)]
        for user, role in users:
            for _ in range(3):
                await world.add_document(stack, ws, user, role, visibility="private")
            out.append((DbContext(role=role, org_id=ws.org, workspace_id=ws.id, user_id=user), 3))
    return out


@pytest.mark.asyncio
async def test_g1_7_ten_thousand_interleaved_transactions_never_see_each_others_context(
    migrated_db: str, stack: Stack
) -> None:
    principals = await _principals(stack)
    pooled = Database(pooled_role_dsn("svc_ingestion", migrated_db), pooled=True)
    rng = random.Random(7)
    plan = [rng.choice(principals) if rng.random() < 0.8 else None for _ in range(TRANSACTIONS)]
    backends: set[int] = set()
    failures: list[str] = []
    kinds: Counter[str] = Counter()

    async def one(item: tuple[DbContext, int] | None) -> None:
        probe = text(
            "SELECT current_setting('app.user_id', true), current_setting('app.workspace_id', true),"
            " pg_backend_pid()"
        )
        rows = text("SELECT owner_user_id, workspace_id FROM documents")
        if item is None:  # no context on a connection other principals have just used
            kinds["unscoped"] += 1
            async with pooled.unscoped_for_self_test() as s:
                setting = (await s.execute(probe)).one()
                await asyncio.sleep(0)
                seen = (await s.execute(rows)).all()
            backends.add(setting[2])
            if setting[0] not in ("", None) or setting[1] not in ("", None) or seen:
                failures.append(f"unscoped saw user={setting[0]!r} rows={len(seen)}")
            return
        ctx, expected = item
        kinds["scoped"] += 1
        async with pooled.scoped(ctx) as s:
            setting = (await s.execute(probe)).one()
            await asyncio.sleep(0)  # let other principals interleave on the shared connections
            seen = (await s.execute(rows)).all()
        backends.add(setting[2])
        if setting[0] != str(ctx.user_id) or setting[1] != str(ctx.workspace_id):
            failures.append(f"context leaked: wanted {ctx.user_id} got {setting[0]}")
        if (
            len(seen) != expected
            or {r[0] for r in seen} != {ctx.user_id}
            or {r[1] for r in seen} != {ctx.workspace_id}
        ):
            failures.append(f"{ctx.role.value} saw {len(seen)} rows of other principals")

    gate = asyncio.Semaphore(CONCURRENCY)

    async def guarded(item: tuple[DbContext, int] | None) -> None:
        async with gate:
            await one(item)

    try:
        await asyncio.gather(*(guarded(item) for item in plan))
    finally:
        await pooled.dispose()
    assert failures == [], failures[:5]
    assert sum(kinds.values()) == TRANSACTIONS
    assert kinds["unscoped"] > 1000, "plenty of no-context transactions reused pooled connections"
    # Proof of multiplexing: ten thousand transactions shared a handful of server connections.
    assert len(backends) <= 8, (
        f"expected pooled reuse of ~5 server connections, saw {len(backends)}"
    )


def test_prepared_statements_work_through_the_pooler(migrated_db: str) -> None:
    """PgBouncer 1.21+ tracks protocol-level prepared statements in transaction mode."""
    dsn = pooled_role_dsn("svc_gateway", migrated_db)
    with psycopg.connect(dsn, prepare_threshold=0) as conn:  # prepare every statement
        for i in range(25):
            with conn.transaction():
                conn.execute("SELECT set_config('app.org_id', %s, true)", (str(i),))
                row = conn.execute("SELECT current_setting('app.org_id', true)").fetchone()
                assert row is not None
                assert row[0] == str(i)
        with conn.transaction():
            row = conn.execute("SELECT current_setting('app.org_id', true)").fetchone()
            assert row is not None
            assert row[0] == "", "the setting never survives its transaction"


def test_the_repository_has_no_session_state_sql_on_the_request_path() -> None:
    assert scan_repository(repo_root()) == []


@pytest.mark.control
@pytest.mark.parametrize(
    "bad",
    [
        "SET statement_timeout = 5000",
        "SET SESSION app.org_id = 'x'",
        "SELECT pg_advisory_lock(42)",
        "SELECT pg_try_advisory_lock(1)",
        "BEGIN; SET statement_timeout = 5",
        "LISTEN changes",
        "NOTIFY changes, 'x'",
        "DECLARE c CURSOR FOR SELECT 1",
        "DECLARE c CURSOR WITH HOLD FOR SELECT 1",
        "PREPARE q AS SELECT 1",
        "DEALLOCATE q",
        "CREATE TEMP TABLE t (a int)",
    ],
)
def test_the_scanner_detects_planted_session_state_statements(bad: str) -> None:
    assert scan_text("planted.py", 1, bad), bad


@pytest.mark.control
@pytest.mark.parametrize(
    "fine",
    [
        "SET LOCAL statement_timeout = 5000",
        "UPDATE orgs SET state = 'active' WHERE id = :id",
        "UPDATE memberships SET state = :s, approved_by = :a WHERE user_id = :u",
        "SELECT set_config('app.org_id', :org, true)",
        "SELECT pg_advisory_xact_lock(hashtextextended(:c, 0))",
        "CREATE TEMP TABLE t (a int) ON COMMIT DROP",
        "set the cache key and notify the user",
        "SELECT count(*) FROM documents",
    ],
)
def test_the_scanner_leaves_transaction_local_forms_alone(fine: str) -> None:
    assert scan_text("fine.py", 1, fine) == []
