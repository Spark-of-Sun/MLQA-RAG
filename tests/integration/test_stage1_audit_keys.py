"""Task 3.20 follow-up from task 3.8: audit keys are created ahead of the month boundary (KD-10, R-51.2, R-60.2).

Core cases only: the job creates the current and next month's key for the control chain and every writable workspace
chain, skips a destroyed workspace, is idempotent, and runs under the identity role's grants and policies.

Real dependencies: PostgreSQL and OpenBao in local key mode. The world is written by the superuser inside a
transaction that is always rolled back (so this also runs on the migrated dev database with
LMQA_TEST_DATABASE=lmqa); the job itself runs as svc_identity. The test organization's OpenBao key is destroyed
afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from lmqa_db import connect_role
from lmqa_db.migrate import drop_database, migrate
from lmqa_keys import KeyRing, OpenBaoProvider, provision_audit_keys
from lmqa_keys.audit_keys import provision_months
from lmqa_models.infra import InfraConfigError
from lmqa_models.settings import load_settings

pytestmark = [pytest.mark.stage1]

# A December far from today, so the year rollover is exercised and no real key exists for these months.
TODAY = date(2031, 12, 31)
MONTHS = [date(2031, 12, 1), date(2032, 1, 1)]


@pytest.mark.unit
def test_provision_months_are_this_month_and_the_next() -> None:
    assert provision_months(TODAY) == MONTHS
    assert provision_months(date(2032, 1, 1)) == [date(2032, 1, 1), date(2032, 2, 1)]


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_auditkeys_{os.getpid()}"
    try:
        migrate(cfg, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(cfg, name)


@pytest.fixture(scope="module")
def provider() -> OpenBaoProvider:
    try:
        bao = OpenBaoProvider()
        bao.ensure_mount()
    except (InfraConfigError, httpx.HTTPError) as exc:  # pragma: no cover - no OpenBao running
        pytest.skip(f"OpenBao unavailable: {exc}")
    return bao


def _keys(conn: psycopg.Connection[Any], org: UUID) -> set[tuple[UUID | None, date]]:
    rows = conn.execute(
        "select workspace_id, month from audit_keys where org_id = %s and state = 'active'", [org]
    ).fetchall()
    return {(r["workspace_id"], r["month"]) for r in rows}


@pytest.mark.integration
def test_next_month_keys_are_created_ahead_for_every_writable_chain(
    database: str, provider: OpenBaoProvider
) -> None:
    ring = KeyRing(provider)
    org, ws, other_ws, gone_ws = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        with (
            connect_role(
                load_settings(), "postgres", database=database, row_factory=dict_row
            ) as conn,
            conn.transaction(force_rollback=True),
        ):
            conn.execute(
                "insert into organizations (id, name, kind, status)"
                " values (%s, 'Audit keys org', 'legal', 'active')",
                [org],
            )
            for w, status in ((ws, "active"), (other_ws, "frozen"), (gone_ws, "destroyed")):
                conn.execute(
                    "insert into workspaces (id, org_id, name, status) values (%s, %s, %s, %s)",
                    [w, org, f"Keys {w}", status],
                )
            ring.ensure_org_key(conn, org)
            ring.ensure_audit_key(conn, org, ws, MONTHS[0])  # one key already exists
            conn.execute("set local role svc_identity")

            @contextmanager
            def transaction() -> Iterator[psycopg.Connection[Any]]:
                with conn.transaction():  # a savepoint inside the rolled-back test transaction
                    yield conn

            first = provision_audit_keys(transaction, ring, TODAY)
            assert first.failed == []
            assert _keys(conn, org) == {
                (chain, month) for chain in (None, ws, other_ws) for month in MONTHS
            }
            # A sealed write on the first day of the next month finds its workspace's key (no fail-closed refusal).
            key = conn.execute(
                "select key_id from audit_public_key(%s, %s, %s)", [org, ws, MONTHS[1]]
            ).fetchone()
            assert key is not None

            again = provision_audit_keys(transaction, ring, TODAY)
            assert again.created == 0
            assert again.failed == []
    finally:
        provider.destroy_now(f"lmqa-org-{org}")
