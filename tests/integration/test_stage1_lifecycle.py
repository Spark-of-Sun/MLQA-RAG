"""Task 3.3: lifecycle machines as data against the real database (R-10 criteria 2, 4, 5 and 6).

Runs on a scratch database built with `lmqa_db.migrate.migrate` and dropped afterwards, or on an already migrated
database named by LMQA_TEST_DATABASE (for example `lmqa`). Trigger tests write as `lmqa_owner` in one transaction
that is always rolled back and switch the caller with transaction-local `app.user_id` / `app.actor`, exactly what
`lmqa_db.scoped()` writes. The identity-service test commits its own uniquely named rows.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import yaml

from identity.service import IdentityService
from lmqa_db import Claims, Database, connect_role, scoped
from lmqa_db.migrate import drop_database, migrate
from lmqa_models import IllegalTransition
from lmqa_models.envfile import ROOT
from lmqa_models.errors import Conflict
from lmqa_models.settings import load_settings
from lmqa_testing.tools import load_tool

pytestmark = [pytest.mark.stage1, pytest.mark.integration]

DOC = yaml.safe_load((ROOT / "contracts" / "state-machines.yaml").read_text(encoding="utf-8"))
GEN = load_tool("state_machine_gen")
WRITABLE = ("users", "organizations", "workspaces", "memberships")


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_lifecycle_{os.getpid()}"
    try:
        migrate(cfg, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(cfg, name)


@pytest.fixture
def tx(database: str) -> Iterator[psycopg.Connection[Any]]:
    with (
        connect_role(load_settings(), "lmqa_owner", database=database) as conn,
        conn.transaction(force_rollback=True),
    ):
        for table in WRITABLE:
            conn.execute(
                f"create policy test_owner_write on {table} for all to lmqa_owner"
                " using (true) with check (true)"
            )
        yield conn


def _as(conn: psycopg.Connection[Any], user: UUID | None = None, actor: str = "") -> None:
    conn.execute(
        "select set_config('app.user_id', %s, true), set_config('app.actor', %s, true)",
        [str(user or ""), actor],
    )


def _world(conn: psycopg.Connection[Any]) -> dict[str, UUID]:
    """An organization with a Super Admin, an active workspace with its admin, a tenant, and a second workspace."""
    ids = {k: uuid4() for k in ("sa", "admin", "tenant", "other", "applicant", "org", "ws", "ws2")}
    for k in ("sa", "admin", "tenant", "other", "applicant"):
        conn.execute(
            "insert into users (id, auth0_sub) values (%s, %s)", [ids[k], f"test|{ids[k]}"]
        )
    conn.execute(
        "insert into organizations (id, name, kind) values (%s, 'Lifecycle Org', 'legal')",
        [ids["org"]],
    )
    for w, status in (("ws", "active"), ("ws2", "pending")):
        conn.execute(
            "insert into workspaces (id, org_id, name, status) values (%s, %s, 'Lifecycle WS', %s)",
            [ids[w], ids["org"], status],
        )
    for user, ws, role, status in (
        ("sa", None, "super_admin", "active"),
        ("admin", "ws", "admin", "active"),
        ("tenant", "ws", "tenant", "active"),
        ("other", "ws", "tenant", "active"),
        ("applicant", "ws2", "admin", "pending_approval"),
    ):
        row = conn.execute(
            "insert into memberships (user_id, org_id, workspace_id, role, status) values (%s, %s, %s, %s, %s)"
            " returning id",
            [ids[user], ids["org"], ids[ws] if ws else None, role, status],
        ).fetchone()
        assert row is not None
        ids[f"m_{user}"] = row[0]
    return ids


def _attempt(conn: psycopg.Connection[Any], sql: str, params: list[Any]) -> str:
    """'ok', or the class of the refusal."""
    try:
        with conn.transaction():
            conn.execute(sql, params)  # type: ignore[arg-type]
    except psycopg.errors.CheckViolation:
        return "pair"
    except psycopg.errors.InsufficientPrivilege:
        return "actor"
    return "ok"


def test_transition_table_equals_the_declaration(tx: psycopg.Connection[Any]) -> None:
    rows = tx.execute(
        "select machine, action, from_state, to_state, actors, guards, effects from state_transitions"
    ).fetchall()
    assert sorted(tuple(r) for r in rows) == GEN.rows(DOC)


def test_every_bound_column_has_its_trigger_and_check(tx: psycopg.Connection[Any]) -> None:
    for (table, column), machines in GEN.bindings(DOC).items():
        trig = tx.execute(
            "select 1 from pg_trigger where tgrelid = %s::regclass and tgname = %s",
            [table, f"transition_{column}"],
        ).fetchone()
        assert trig, f"{table}.{column} has no transition trigger"
        checks = tx.execute(
            "select pg_get_constraintdef(oid) from pg_constraint where conrelid = %s::regclass and contype = 'c'"
            " and pg_get_constraintdef(oid) ~ %s",
            [table, rf"\({column} = ANY"],
        ).fetchall()
        states = {s for m in machines for s in DOC["machines"][m]["states"]}
        assert checks and all(f"'{s}'" in checks[0][0] for s in states), f"{table}.{column}"


@pytest.mark.parametrize(
    ("table", "machine"), [("memberships", "membership"), ("workspaces", "workspace")]
)
def test_generated_pairs_declared_succeed_and_undeclared_fail(
    tx: psycopg.Connection[Any], table: str, machine: str
) -> None:
    """R-10.2 and R-10.4: every state pair of the machine, tried as the owner (held to the pairs, not the actors)."""
    spec = DOC["machines"][machine]
    declared = {(t["from"], t["to"]) for t in spec["transitions"].values()}
    ids = _world(tx)
    row = ids["m_tenant"] if table == "memberships" else ids["ws"]
    failures = []
    for frm, to in itertools.permutations(spec["states"], 2):
        with tx.transaction(force_rollback=True):
            tx.execute("alter table " + table + " disable trigger transition_status")
            tx.execute(f"update {table} set status = %s where id = %s", [frm, row])  # noqa: S608
            tx.execute("alter table " + table + " enable trigger transition_status")
            got = _attempt(tx, f"update {table} set status = %s where id = %s", [to, row])  # noqa: S608
        if (got == "ok") != ((frm, to) in declared):
            failures.append((frm, to, got))
    assert failures == []


def test_membership_actors_are_enforced_by_the_database(tx: psycopg.Connection[Any]) -> None:
    """R-10.4 and R-10.5: the approver may, the member, an unrelated user and a missing context may not."""
    ids = _world(tx)
    sql = "update memberships set status = %s where id = %s"
    cases = [
        (ids["tenant"], "", "suspended", ids["m_tenant"], "actor"),  # the member, on their own row
        (ids["other"], "", "suspended", ids["m_tenant"], "actor"),  # another tenant
        (
            ids["sa"],
            "",
            "suspended",
            ids["m_tenant"],
            "actor",
        ),  # the Super Admin is not a tenant's approver
        (ids["admin"], "", "suspended", ids["m_tenant"], "ok"),  # the workspace admin is
        (ids["sa"], "", "active", ids["m_applicant"], "ok"),  # the Super Admin approves an admin
        (ids["admin"], "", "active", ids["m_applicant"], "actor"),
        (None, "identity:worker", "suspended", ids["m_tenant"], "ok"),  # cascade_suspend
        (
            None,
            "identity:worker",
            "rejected",
            ids["m_applicant"],
            "actor",
        ),  # only an approver rejects
    ]
    for user, actor, to, mid, expected in cases:
        with tx.transaction(force_rollback=True):
            _as(tx, user, actor)
            assert _attempt(tx, sql, [to, mid]) == expected, (user, actor, to)
    with tx.transaction(force_rollback=True):  # a stranger from another organization
        _as(tx, uuid4())
        assert _attempt(tx, sql, ["suspended", ids["m_tenant"]]) == "actor"


def test_member_cannot_touch_their_row_but_may_withdraw_a_pending_one(
    tx: psycopg.Connection[Any],
) -> None:
    ids = _world(tx)
    _as(tx, ids["tenant"])
    assert (
        _attempt(tx, "update memberships set co_owner = true where id = %s", [ids["m_tenant"]])
        == "actor"
    )
    assert _attempt(tx, "delete from memberships where id = %s", [ids["m_tenant"]]) == "actor"
    _as(tx, ids["applicant"])
    assert _attempt(tx, "delete from memberships where id = %s", [ids["m_applicant"]]) == "ok"


def test_identity_routes_enforce_the_machine_and_read_no_content(database: str) -> None:
    """R-10.5 at the service behind the {action} routes, and the Manage Admins / Manage Tenants reads as svc_identity
    (which holds no grant on documents or queries)."""
    cfg = load_settings()
    db = Database(cfg, database=database, services=("identity",))
    db.open()
    try:
        svc = IdentityService(cfg, db)
        tag = uuid4().hex[:8]
        sa = svc.resolve(f"test|sa-{tag}", f"sa-{tag}@x.test", "SA")
        org_id = svc.create_organization(sa, f"Org {tag}", "legal")["organization_id"]
        sa = svc.resolve(f"test|sa-{tag}", None, None)
        admin = svc.resolve(f"test|ad-{tag}", f"ad-{tag}@x.test", "Admin")
        tenant = svc.resolve(f"test|tn-{tag}", f"tn-{tag}@x.test", "Tenant")
        with scoped(db.service("identity"), Claims(actor="test")) as c:
            ws = c.execute(
                "insert into workspaces (org_id, name) values (%s, 'Workspace') returning id",
                [org_id],
            ).fetchone()["id"]
            admin_mid = c.execute(
                "insert into memberships (user_id, org_id, workspace_id, role, status)"
                " values (%s, %s, %s, 'admin', 'pending_approval') returning id",
                [admin.user_id, org_id, ws],
            ).fetchone()["id"]
            tenant_mid = c.execute(
                "insert into memberships (user_id, org_id, workspace_id, role, status)"
                " values (%s, %s, %s, 'tenant', 'pending_approval') returning id",
                [tenant.user_id, org_id, ws],
            ).fetchone()["id"]
        assert svc.decide_admin(sa, str(admin_mid), "approve")["status"] == "active"
        with pytest.raises(Conflict):  # approve again: the row is no longer pending_approval
            svc.decide_admin(sa, str(admin_mid), "approve")
        admin = svc.resolve(f"test|ad-{tag}", None, None)
        rows = svc.list_admins(sa)
        assert [r["id"] for r in rows] == [str(admin_mid)] and "documents" not in rows[0]
        assert svc.decide_member(admin, str(tenant_mid), "approve")["status"] == "active"
        tenant = svc.resolve(f"test|tn-{tag}", None, None)
        with pytest.raises(IllegalTransition) as err:
            svc.decide_admin(admin, str(admin_mid), "suspend")  # the admin's own membership
        assert err.value.status == 403
        members = svc.list_members(admin)
        assert [r["id"] for r in members] == [str(tenant_mid)] and "questions" not in members[0]
    finally:
        db.close()
