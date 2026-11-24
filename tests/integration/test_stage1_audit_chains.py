"""Task 3.8: audit chains (R-60 criteria 2 and 4, R-61 criteria 1, 4 and 5; KD-10, DEV-18).

Core cases only: chains verify after appends to workspace and control chains, tampering is detected, UPDATE, DELETE
and TRUNCATE are rejected by trigger, a sealed payload opens only with its workspace-month key, and concurrent
appends to one chain do not fork it. Property tests 3.16 and 3.17 and edge cases come later.

Real dependencies: PostgreSQL (writes go through `audit_append` as the runtime role `lmqa_app`) and OpenBao in
local key mode (audit private keys are wrapped by the organization CMK). Most tests run in a superuser transaction
that is always rolled back; the concurrency test commits, so it removes its own rows afterwards. Both run on the
migrated dev database too (LMQA_TEST_DATABASE=lmqa).
"""

from __future__ import annotations

import hashlib
import itertools
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any, LiteralString
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

import lmqa_audit
from audit.anchor import PayloadReader
from lmqa_audit.sealed import current_month
from lmqa_db import connect_role
from lmqa_db.migrate import drop_database, migrate
from lmqa_keys import KeyRing, OpenBaoProvider
from lmqa_models.infra import InfraConfigError
from lmqa_models.settings import load_settings
from lmqa_security.sealing import unseal

pytestmark = [pytest.mark.stage1, pytest.mark.integration]


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_audit_{os.getpid()}"
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


def _superuser(database: str, **kwargs: Any) -> psycopg.Connection[Any]:
    return connect_role(
        load_settings(), "postgres", database=database, row_factory=dict_row, **kwargs
    )


def _new_org(conn: psycopg.Connection[Any], workspaces: int) -> tuple[UUID, list[UUID]]:
    org = uuid4()
    conn.execute(
        "insert into organizations (id, name, kind, status) values (%s, 'Audit org', 'legal', 'active')",
        [org],
    )
    ws = [uuid4() for _ in range(workspaces)]
    for w in ws:
        conn.execute(
            "insert into workspaces (id, org_id, name, status) values (%s, %s, %s, 'active')",
            [w, org, f"Audit {w}"],
        )
    return org, ws


@dataclass
class World:
    conn: psycopg.Connection[Any]
    org: UUID
    ws: UUID
    other_ws: UUID

    def append(self, workspace: UUID | None, action: str = "test.event", **kwargs: Any) -> int:
        """Write as the runtime role, the way services do."""
        self.conn.execute("set local role lmqa_app")
        try:
            return lmqa_audit.append(
                self.conn, org_id=self.org, workspace_id=workspace, action=action, **kwargs
            )
        finally:
            self.conn.execute("reset role")

    def event(self, event_id: int) -> dict[str, Any]:
        row = self.conn.execute("select * from audit_events where id = %s", [event_id]).fetchone()
        assert row is not None
        return dict(row)

    def verify(self) -> lmqa_audit.ChainStatus:
        return lmqa_audit.verify_chain(self.conn, self.org)


@pytest.fixture
def world(database: str) -> Iterator[World]:
    with _superuser(database) as conn, conn.transaction(force_rollback=True):
        org, (ws, other_ws) = _new_org(conn, 2)
        yield World(conn, org, ws, other_ws)


def test_chains_verify_after_appends(world: World) -> None:
    """R-61.1: one chain per workspace plus the control chain; each links seq 1..n from the zero hash."""
    plan = [world.ws, None, world.ws, world.other_ws, world.ws, None]
    ids = [world.append(w, target_type="document", target_id=uuid4()) for w in plan]
    chains = world.conn.execute(
        "select id, workspace_id, head_seq from audit_chains where org_id = %s", [world.org]
    ).fetchall()
    assert {(c["workspace_id"], c["head_seq"]) for c in chains} == {
        (world.ws, 3),
        (world.other_ws, 1),
        (None, 2),
    }
    for c in chains:
        events = world.conn.execute(
            "select seq, prev_hash, hash, workspace_id from audit_events where chain_id = %s order by seq",
            [c["id"]],
        ).fetchall()
        assert [e["seq"] for e in events] == list(range(1, c["head_seq"] + 1))
        assert events[0]["prev_hash"] == "0" * 64
        assert all(e["workspace_id"] == c["workspace_id"] for e in events)
        assert all(b["prev_hash"] == a["hash"] for a, b in itertools.pairwise(events))
        assert lmqa_audit.verify_chain_id(world.conn, c["id"]).ok
    assert world.verify() == lmqa_audit.ChainStatus(True, len(ids), None)


def _tamper(conn: psycopg.Connection[Any], sql: LiteralString, params: list[Any]) -> None:
    # A superuser can switch the triggers off for its own session.
    conn.execute("set local session_replication_role = replica")
    conn.execute(sql, params)
    conn.execute("set local session_replication_role = origin")


@pytest.mark.parametrize("change", ["meta", "delete_middle", "delete_tail", "reorder"])
def test_tampering_is_detected(world: World, change: str) -> None:
    """R-61.1: a changed, deleted or reordered event breaks verification at that position."""
    ids = [world.append(world.ws, payload={"n": n}) for n in range(5)]
    world.append(None)
    assert world.verify().ok
    middle = world.event(ids[2])
    with world.conn.transaction(force_rollback=True):
        if change == "meta":
            _tamper(
                world.conn, "update audit_events set meta = '{\"n\": 99}' where id = %s", [ids[2]]
            )
            expected = ids[2]
        elif change == "delete_middle":
            _tamper(world.conn, "delete from audit_events where id = %s", [ids[2]])
            expected = ids[3]
        elif change == "delete_tail":
            _tamper(world.conn, "delete from audit_events where id = %s", [ids[4]])
            expected = ids[4]  # the head still names the deleted event
        else:
            _tamper(
                world.conn,
                "update audit_events set seq = case id when %s then %s else %s end where id in (%s, %s)",
                [ids[2], middle["seq"] + 1, middle["seq"], ids[2], ids[3]],
            )
            expected = ids[3]
        status = world.verify()
        assert not status.ok
        assert status.first_bad_id == expected
    assert world.verify().ok


def test_update_delete_and_truncate_are_rejected(world: World) -> None:
    """R-61.4: the triggers refuse even the superuser; runtime roles hold no write grant at all."""
    event_id = world.append(world.ws)
    chain = world.event(event_id)["chain_id"]
    assert world.conn.execute(
        "select audit_checkpoint(%s, 1, 'manual', 'test')", [chain]
    ).fetchone()
    for sql in (
        "update audit_events set action = 'x' where chain_id = %s",
        "delete from audit_events where chain_id = %s",
        "delete from audit_chains where id = %s",
        "update audit_checkpoints set last_hash = 'x' where chain_id = %s",
        "delete from audit_checkpoints where chain_id = %s",
    ):
        with (
            world.conn.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.RaiseException),
        ):
            world.conn.execute(sql, [chain])
    for table in ("audit_events", "audit_payloads", "audit_checkpoints", "audit_chains"):
        with (
            world.conn.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.RaiseException),
        ):
            world.conn.execute(f"truncate {table} cascade")
    with world.conn.transaction(force_rollback=True):
        world.conn.execute("set local role lmqa_app")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            world.conn.execute("update audit_events set action = 'x' where id = %s", [event_id])
    assert world.verify().ok


def test_sealed_payload_opens_only_with_its_workspace_month_key(
    world: World, provider: OpenBaoProvider
) -> None:
    """R-60.2, R-60.4: content is sealed to the chain's workspace-month key; the chain holds its SHA-256."""
    ring = KeyRing(provider)
    month = current_month()
    next_month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    try:
        own = ring.ensure_audit_key(world.conn, world.org, world.ws, month)
        ring.ensure_audit_key(world.conn, world.org, world.other_ws, month)
        ring.ensure_audit_key(world.conn, world.org, world.ws, next_month)
        content = {
            "question": "What is the cure period?",
            "chunks": ["c1", "c2"],
            "answer": "30 days.",
        }
        event_id = world.append(world.ws, action="query.answered", content=content)
        event = world.event(event_id)
        payload = world.conn.execute(
            "select p.ciphertext, p.key_id, k.public_key from audit_payloads p join audit_keys k on k.id = p.key_id"
            " where p.event_id = %s",
            [event_id],
        ).fetchone()
        assert payload is not None
        ciphertext = bytes(payload["ciphertext"])
        assert bytes(payload["public_key"]) == own.public_key
        assert event["payload_key_id"] == payload["key_id"]
        assert event["payload_ct_sha256"] == hashlib.sha256(ciphertext).hexdigest()
        assert b"cure period" not in ciphertext
        assert event["meta"] == {}

        def opens(workspace: UUID, key_month: date, bound_ws: UUID | None = None) -> bool:
            key = ring.audit_private_key(world.conn, world.org, workspace, key_month)
            assert key is not None
            try:
                got = unseal(
                    ciphertext,
                    key,
                    org_id=world.org,
                    workspace_id=bound_ws or workspace,
                    month=month,
                    action="query.answered",
                )
            except Exception:
                return False
            return got == content

        assert opens(world.ws, month)
        assert not opens(world.other_ws, month)
        assert not opens(world.ws, next_month)
        assert not opens(world.ws, month, bound_ws=world.other_ws)  # copied to another chain
        assert (
            PayloadReader(provider).payload(world.conn, event) == content
        )  # the audit service's read path
        assert world.verify().ok

        # A chain without an active key for the month fails closed, and nothing is written.
        world.conn.execute(
            "insert into workspaces (id, org_id, name, status) values (%s, %s, 'No key', 'active')",
            [no_key := uuid4(), world.org],
        )
        with (
            world.conn.transaction(force_rollback=True),
            pytest.raises(lmqa_audit.AuditUnavailableError),
        ):
            world.append(no_key, content=content)
        # The database refuses a payload sealed to another chain's key.
        with (
            world.conn.transaction(force_rollback=True),
            pytest.raises(psycopg.errors.InvalidParameterValue),
        ):
            world.conn.execute(
                "select audit_append(%s, %s, null, 'x', null, null, '{}', 'info', null, %s, %s)",
                [world.org, world.other_ws, ciphertext, payload["key_id"]],
            )
    finally:
        provider.destroy_now(f"lmqa-org-{world.org}")


def test_concurrent_appends_do_not_fork(database: str) -> None:
    """R-61.1: a second writer waits for the first's chain lock and links to its event; a burst stays linear."""
    with _superuser(database, autocommit=True) as setup:
        org, (ws,) = _new_org(setup, 1)
    try:
        with _superuser(database) as first, _superuser(database) as second:
            a = lmqa_audit.append(first, org_id=org, workspace_id=ws, action="test.first")
            done: dict[str, int] = {}
            waiter = threading.Thread(
                target=lambda: done.setdefault(
                    "b",
                    lmqa_audit.append(second, org_id=org, workspace_id=ws, action="test.second"),
                )
            )
            waiter.start()
            time.sleep(0.5)
            assert "b" not in done, "the second writer must wait for the chain lock"
            first.commit()
            waiter.join(timeout=10)
            second.commit()
        b = done["b"]

        def burst() -> None:
            with _superuser(database) as conn:
                for _ in range(10):
                    lmqa_audit.append(conn, org_id=org, workspace_id=ws, action="test.burst")
                    conn.commit()

        threads = [threading.Thread(target=burst) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        with _superuser(database) as conn:
            rows = conn.execute(
                "select e.id, e.seq, e.prev_hash, e.hash from audit_events e join audit_chains c on c.id = e.chain_id"
                " where c.org_id = %s and c.workspace_id = %s order by e.seq",
                [org, ws],
            ).fetchall()
            by_id = {r["id"]: r for r in rows}
            assert by_id[b]["seq"] == by_id[a]["seq"] + 1
            assert by_id[b]["prev_hash"] == by_id[a]["hash"]
            assert [r["seq"] for r in rows] == list(range(1, 43))
            assert len({r["prev_hash"] for r in rows}) == 42  # no two events share a parent
            assert lmqa_audit.verify_chain(conn, org) == lmqa_audit.ChainStatus(True, 42, None)
    finally:
        with _superuser(database) as conn:
            conn.execute("set local session_replication_role = replica")
            for sql in (
                "delete from audit_payloads where chain_id in (select id from audit_chains where org_id = %s)",
                "delete from audit_events where org_id = %s",
                "delete from audit_checkpoints where org_id = %s",
                "delete from audit_chains where org_id = %s",
                "delete from workspaces where org_id = %s",
                "delete from organizations where id = %s",
            ):
                conn.execute(sql, [org])
