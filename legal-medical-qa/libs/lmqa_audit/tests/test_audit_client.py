"""G9.2 audit sealing, on real PostgreSQL and a real OpenBao key provider."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text

from lmqa_audit import (
    AuditEvent,
    AuditKeyDestroyedError,
    AuditKeyManager,
    AuditKeyMissingError,
    AuditReader,
    AuditWriter,
    month_start,
)
from lmqa_db import ContextRole
from lmqa_keys import KeyService, OpenBaoProvider
from lmqa_testing import world
from lmqa_testing.pg import role_dsn

pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage9]


@pytest_asyncio.fixture
async def provider():
    async with OpenBaoProvider(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
    ) as p:
        yield p


async def _setup(stack, provider):
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, ws)
    ids = await KeyService(provider).provision_org(org.id)
    async with stack.identity.scoped(world.SYSTEM) as s:
        await AuditKeyManager().ensure_month_key(
            s, provider, ids.cmk_id, org.id, ws.id, month_start()
        )
    return org, ws, tenant, ids.cmk_id


def _admin(ws):
    return world.ctx(ContextRole.ADMIN, ws.org, ws.id, ws.admin)


@pytest.mark.asyncio
async def test_a_sealed_payload_is_read_only_by_the_audit_service(stack, provider) -> None:
    org, ws, tenant, cmk = await _setup(stack, provider)
    secret = {"question": "What is the notice period in clause 4.2?", "answer": "Thirty days."}
    request = uuid4()
    async with stack.generation.scoped(world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant)) as s:
        event = await AuditWriter().append(
            s,
            org.id,
            ws.id,
            AuditEvent(
                "query.completed",
                "ok",
                "tenant",
                tenant,
                "tenant",
                request_id=request,
                payload=secret,
            ),
        )
    async with stack.audit_reader.scoped(_admin(ws)) as s:
        assert await AuditReader().read_payload(s, provider, cmk, org.id, event) == secret
        raw = (
            await s.execute(
                text("SELECT ciphertext FROM audit_payload WHERE event_id = :e"), {"e": event}
            )
        ).scalar_one()
    assert b"notice period" not in bytes(raw), "the stored payload is ciphertext"


@pytest.mark.asyncio
async def test_writers_cannot_read_payloads_or_private_keys(
    migrated_db: str, stack, provider
) -> None:
    await _setup(stack, provider)
    for role in (
        "svc_gateway",
        "svc_generation",
        "svc_retrieval",
        "svc_validator",
        "svc_ingestion",
        "svc_identity",
    ):
        with psycopg.connect(role_dsn(role, migrated_db)) as conn:
            for statement in (
                "SELECT ciphertext FROM audit_payload",
                "SELECT wrapped_private_key FROM audit_keys",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(statement)
            with conn.transaction():  # the public half is readable, the private half is not
                conn.execute("SELECT public_key FROM audit_keys LIMIT 1")


@pytest.mark.asyncio
async def test_a_missing_month_key_stops_the_write_and_leaves_no_event(stack) -> None:
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)  # no audit key was created for this workspace
    with pytest.raises(AuditKeyMissingError):
        async with stack.gateway.scoped(_admin(ws)) as s:
            await AuditWriter().append(
                s,
                org.id,
                ws.id,
                AuditEvent(
                    "segment.released", "ok", "workspace", ws.admin, "admin", payload={"x": 1}
                ),
            )
    async with stack.audit_reader.scoped(_admin(ws)) as s:
        assert (await s.execute(text("SELECT count(*) FROM audit_event"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_g9_2_destroying_a_months_key_makes_payloads_unreadable_but_the_chain_still_verifies(
    stack, provider
) -> None:
    org, ws, _tenant, cmk = await _setup(stack, provider)
    events = []
    for i in range(3):
        async with stack.generation.scoped(_admin(ws)) as s:
            events.append(
                await AuditWriter().append(
                    s,
                    org.id,
                    ws.id,
                    AuditEvent(f"e{i}", "ok", "workspace", ws.admin, "admin", payload={"n": i}),
                )
            )
    async with stack.audit_reader.scoped(_admin(ws)) as s:
        assert (await AuditReader().read_payload(s, provider, cmk, org.id, events[1]))["n"] == 1
    async with stack.audit_reader.scoped(world.SYSTEM) as s:
        await AuditReader().destroy_month_key(s, ws.id, month_start())
    async with stack.audit_reader.scoped(_admin(ws)) as s:
        with pytest.raises(AuditKeyDestroyedError):
            await AuditReader().read_payload(s, provider, cmk, org.id, events[1])
    async with stack.audit_reader.scoped(world.SYSTEM) as s:
        assert (
            await s.execute(text("SELECT audit_verify(:c)"), {"c": f"ws:{ws.id}"})
        ).scalar_one() is None


@pytest.mark.asyncio
async def test_payload_visibility_follows_the_role_rules(stack, provider) -> None:
    org, ws, tenant, cmk = await _setup(stack, provider)
    other = await world.create_tenant(stack, ws)
    async with stack.generation.scoped(world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant)) as s:
        mine = await AuditWriter().append(
            s,
            org.id,
            ws.id,
            AuditEvent("q", "ok", "tenant", tenant, "tenant", payload={"who": "tenant"}),
        )
    reader = AuditReader()
    async with stack.audit_reader.scoped(world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant)) as s:
        assert (await reader.read_payload(s, provider, cmk, org.id, mine))["who"] == "tenant"
    async with stack.audit_reader.scoped(_admin(ws)) as s:
        assert (await reader.read_payload(s, provider, cmk, org.id, mine))["who"] == "tenant"
    for ctx in (
        world.ctx(ContextRole.TENANT, ws.org, ws.id, other),
        world.ctx(ContextRole.SUPER_ADMIN, org.id, None, org.super_admin),
    ):
        async with stack.audit_reader.scoped(ctx) as s:
            with pytest.raises(LookupError):
                await reader.read_payload(s, provider, cmk, org.id, mine)


@pytest.mark.asyncio
async def test_each_month_needs_its_own_key_and_a_foreign_org_cannot_write_into_this_chain(
    stack, provider
) -> None:
    org, ws, _t, _cmk = await _setup(stack, provider)
    future = datetime(2099, 1, 15, tzinfo=UTC)
    with pytest.raises(AuditKeyMissingError):
        async with stack.gateway.scoped(_admin(ws)) as s:
            await AuditWriter().append(
                s,
                org.id,
                ws.id,
                AuditEvent("x", "ok", "workspace", payload={"a": 1}),
                moment=future,
            )
    other_org = await world.create_org(stack)
    other_ws = await world.create_workspace(stack, other_org)
    with pytest.raises(Exception, match="does not match the request context"):
        async with stack.gateway.scoped(_admin(ws)) as s:
            await AuditWriter().append(
                s, other_org.id, other_ws.id, AuditEvent("forged", "ok", "workspace")
            )
