"""G1.8: hash-chained, insert-only audit written only through audit_append (doc 13.3)."""

from __future__ import annotations

import asyncio
import itertools
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from lmqa_db import ContextRole, DbContext
from lmqa_db.bootstrap import with_database
from lmqa_testing import world
from lmqa_testing.pg import fresh_database, role_dsn, superuser_dsn

if TYPE_CHECKING:
    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

APPEND = text(
    "SELECT audit_append(:chain, :org, :ws, :actor, :role, :action, :target, 'ok', NULL, NULL, NULL, NULL,"
    " :scope, :payload, 'k1')"
)


async def _append(
    stack: Stack,
    ws: world.Workspace,
    action: str,
    payload: bytes | None = None,
    scope: str = "workspace",
) -> UUID:
    ctx = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    async with stack.ingestion.scoped(ctx) as s:
        return (
            await s.execute(
                APPEND,
                {
                    "chain": f"ws:{ws.id}",
                    "org": ws.org,
                    "ws": ws.id,
                    "actor": ws.admin,
                    "role": "admin",
                    "action": action,
                    "target": None,
                    "scope": scope,
                    "payload": payload,
                },
            )
        ).scalar_one()


async def _verify(stack: Stack, chain: str) -> int | None:
    async with stack.audit_reader.scoped(world.SYSTEM) as s:
        return (await s.execute(text("SELECT audit_verify(:c)"), {"c": chain})).scalar_one()


async def _workspace(stack: Stack) -> world.Workspace:
    org = await world.create_org(stack)
    return await world.create_workspace(stack, org)


@pytest.mark.asyncio
async def test_a_chain_builds_and_verifies(stack: Stack) -> None:
    ws = await _workspace(stack)
    for i in range(6):
        await _append(stack, ws, f"test.event.{i}", payload=bytes([i]) * 8 if i % 2 else None)
    assert await _verify(stack, f"ws:{ws.id}") is None
    ctx = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    async with stack.audit_reader.scoped(ctx) as s:
        rows = (
            await s.execute(text("SELECT seq, prev_hash, hash FROM audit_event ORDER BY seq"))
        ).all()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0][1] == bytes(32), "genesis prev_hash is 32 zero bytes"
    for earlier, later in itertools.pairwise(rows):
        assert later[1] == earlier[2], "each event links to the previous hash"


@pytest.mark.asyncio
async def test_concurrent_appends_stay_contiguous_and_valid(stack: Stack) -> None:
    ws = await _workspace(stack)
    await asyncio.gather(*(_append(stack, ws, f"concurrent.{i}") for i in range(25)))
    assert await _verify(stack, f"ws:{ws.id}") is None
    ctx = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    async with stack.audit_reader.scoped(ctx) as s:
        seqs = [
            r[0] for r in (await s.execute(text("SELECT seq FROM audit_event ORDER BY seq"))).all()
        ]
    assert seqs == list(range(1, 26))


@pytest.mark.asyncio
async def test_update_and_delete_are_rejected_for_every_role(
    migrated_db: str, stack: Stack
) -> None:
    ws = await _workspace(stack)
    event = await _append(stack, ws, "test.immutable", payload=b"\x09" * 8)
    for role in ("svc_identity", "svc_ingestion", "svc_audit_reader", "svc_gateway"):
        with psycopg.connect(role_dsn(role, migrated_db)) as conn:
            for statement in (
                "UPDATE audit_event SET action = 'tampered'",
                "DELETE FROM audit_event",
                "TRUNCATE audit_event",
                "UPDATE audit_payload SET key_id = 'x'",
                "DELETE FROM audit_payload",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(statement)  # type: ignore[arg-type]
    # Even a superuser (who bypasses RLS and grants) is stopped by the triggers.
    with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as conn:
        for statement in (
            "UPDATE audit_event SET action = 'tampered'",
            "DELETE FROM audit_event",
            "UPDATE audit_payload SET key_id = 'x'",
            "DELETE FROM audit_payload",
            "TRUNCATE audit_event, audit_payload",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="insert-only"):
                conn.execute(statement)  # type: ignore[arg-type]
    assert event is not None


@pytest.mark.asyncio
async def test_services_cannot_insert_audit_rows_directly(migrated_db: str, stack: Stack) -> None:
    ws = await _workspace(stack)
    for role in ("svc_identity", "svc_ingestion", "svc_gateway", "svc_audit_reader"):
        with (
            psycopg.connect(role_dsn(role, migrated_db)) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(
                "INSERT INTO audit_event (chain_id, seq, org_id, action, outcome, scope, prev_hash, hash)"
                " VALUES ('x', 1, %s, 'forged', 'ok', 'org', '\\x00', '\\x00')",
                (ws.org,),
            )


@pytest.mark.asyncio
async def test_event_scope_must_match_the_request_context(stack: Stack) -> None:
    ws = await _workspace(stack)
    other = await _workspace(stack)
    ctx = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    with pytest.raises(DBAPIError, match="does not match the request context"):
        async with stack.ingestion.scoped(ctx) as s:
            await s.execute(
                APPEND,
                {
                    "chain": f"ws:{other.id}",
                    "org": other.org,
                    "ws": other.id,
                    "actor": ws.admin,
                    "role": "admin",
                    "action": "forged.cross.workspace",
                    "target": None,
                    "scope": "workspace",
                    "payload": None,
                },
            )
    with pytest.raises(DBAPIError, match="chain does not belong"):
        async with stack.ingestion.scoped(ctx) as s:
            await s.execute(
                APPEND,
                {
                    "chain": f"ws:{uuid4()}",
                    "org": ws.org,
                    "ws": ws.id,
                    "actor": ws.admin,
                    "role": "admin",
                    "action": "x",
                    "target": None,
                    "scope": "workspace",
                    "payload": None,
                },
            )


@pytest.mark.asyncio
async def test_tampering_on_an_isolated_copy_is_detected() -> None:
    name = "lmqa_audit_tamper"
    fresh_database(name)
    from lmqa_db import Database  # noqa: PLC0415
    from lmqa_testing.fixtures import Stack as S  # noqa: PLC0415

    def make(role: str) -> Database:
        return Database(role_dsn(role, name), pooled=False, use_null_pool=True)

    local = S(
        gateway=make("svc_gateway"),
        identity=make("svc_identity"),
        ingestion=make("svc_ingestion"),
        retrieval=make("svc_retrieval"),
        generation=make("svc_generation"),
        validator=make("svc_validator"),
        audit_reader=make("svc_audit_reader"),
        reconciler=make("svc_reconciler"),
    )
    try:

        async def build() -> tuple[str, UUID]:
            ws = await _workspace(local)
            events = [await _append(local, ws, f"evt.{i}", payload=b"\x07" * 8) for i in range(5)]
            chain = f"ws:{ws.id}"
            assert await _verify(local, chain) is None
            return chain, events[2]  # the third event is the one we tamper with

        edit, edit_event = await build()
        payload_chain, payload_event = await build()
        gap, gap_event = await build()
        intact, _ = await build()

        with psycopg.connect(with_database(superuser_dsn(), name), autocommit=True) as conn:
            conn.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_immutable")
            conn.execute("ALTER TABLE audit_payload DISABLE TRIGGER audit_payload_immutable")
            # 1. alter a field the hash covers
            conn.execute("UPDATE audit_event SET action = 'edited' WHERE id = %s", (edit_event,))
            # 2. alter the payload hash the chain commits to
            conn.execute(
                "UPDATE audit_event SET payload_hash = '\\x00' WHERE id = %s", (payload_event,)
            )
            # 3. delete an event (and its payload): the sequence has a gap
            conn.execute("DELETE FROM audit_payload WHERE event_id = %s", (gap_event,))
            conn.execute("DELETE FROM audit_event WHERE id = %s", (gap_event,))

        assert await _verify(local, edit) == 3, "an edited field breaks the hash at that event"
        assert await _verify(local, payload_chain) == 3, "a changed payload hash breaks the hash"
        assert await _verify(local, gap) == 4, "a deleted event is reported at the gap"
        assert await _verify(local, intact) is None, "an untouched chain still verifies"
    finally:
        for db in (
            local.gateway,
            local.identity,
            local.ingestion,
            local.retrieval,
            local.generation,
            local.validator,
            local.audit_reader,
            local.reconciler,
        ):
            await db.dispose()


@pytest.mark.asyncio
async def test_hash_does_not_depend_on_the_session_time_zone(
    migrated_db: str, stack: Stack
) -> None:
    ws = await _workspace(stack)
    await _append(stack, ws, "tz.event")
    ctx = DbContext(role=ContextRole.ADMIN, org_id=ws.org, workspace_id=ws.id, user_id=ws.admin)
    async with stack.ingestion.scoped(ctx) as s:
        await s.execute(text("SET LOCAL TIME ZONE 'Pacific/Kiritimati'"))
        await s.execute(
            APPEND,
            {
                "chain": f"ws:{ws.id}",
                "org": ws.org,
                "ws": ws.id,
                "actor": ws.admin,
                "role": "admin",
                "action": "tz.event.2",
                "target": None,
                "scope": "workspace",
                "payload": None,
            },
        )
    assert await _verify(stack, f"ws:{ws.id}") is None
    with psycopg.connect(role_dsn("svc_audit_reader", migrated_db)) as conn:
        conn.execute("SET TIME ZONE 'America/Los_Angeles'")
        conn.execute("SELECT set_config('app.role', 'system', true)")
        row = conn.execute("SELECT audit_verify(%s)", (f"ws:{ws.id}",)).fetchone()
        assert row is not None
        assert row[0] is None
