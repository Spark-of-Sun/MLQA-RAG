"""Task 3.2: tenancy and membership schema (R-1 criteria 3, 4 and 7; R-78; Q-23; DEV-17 schema part).

Runs on a scratch database built with `lmqa_db.migrate.migrate` and dropped afterwards, or on an already migrated
database named by LMQA_TEST_DATABASE (for example the dev database `lmqa`). The schema tests write as `lmqa_owner`
inside one transaction that is always rolled back; a temporary owner policy stands in for a role that may write
(FORCE RLS applies to the owner too). The identity-service test commits its own uniquely named rows.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from identity.service import IdentityService
from lmqa_db import Claims, Database, connect_role, scoped
from lmqa_db.migrate import drop_database, migrate
from lmqa_models.envfile import ROOT
from lmqa_models.settings import load_settings

pytestmark = [pytest.mark.stage1, pytest.mark.integration]

LIVE = ("pending_approval", "active", "suspended")
STATES = ("pending_approval", "active", "rejected", "suspended", "removed")
MEMBERSHIP_PAIRS = {
    (t["from"], t["to"])
    for t in yaml.safe_load(
        (ROOT / "contracts" / "state-machines.yaml").read_text(encoding="utf-8")
    )["machines"]["membership"]["transitions"].values()
}
WRITABLE = (
    "users",
    "organizations",
    "workspaces",
    "memberships",
    "conversations",
    "queries",
    "query_segments",
)
DB_SETTINGS = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_tenancy_{os.getpid()}"
    try:
        migrate(cfg, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(cfg, name)


@pytest.fixture
def tx(database: str) -> Iterator[psycopg.Connection[Any]]:
    """lmqa_owner in one transaction that is always rolled back. CREATE POLICY locks the tables until then, so the
    fixture is per test: other connections (the identity-service test) are not blocked."""
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


def _users(conn: psycopg.Connection[Any], n: int) -> list[UUID]:
    ids = [uuid4() for _ in range(n)]
    for u in ids:
        conn.execute("insert into users (id, auth0_sub) values (%s, %s)", [u, f"test|{u}"])
    return ids


def _org(
    conn: psycopg.Connection[Any], workspaces: int, status: str = "active"
) -> tuple[UUID, list[UUID]]:
    org = uuid4()
    conn.execute(
        "insert into organizations (id, name, kind) values (%s, 'Test Org', 'legal')", [org]
    )
    ws = [uuid4() for _ in range(workspaces)]
    for w in ws:
        conn.execute(
            "insert into workspaces (id, org_id, name, status) values (%s, %s, 'Test Workspace', %s)",
            [w, org, status],
        )
    return org, ws


def _member(
    conn: psycopg.Connection[Any],
    user: UUID,
    scope: tuple[UUID, UUID | None],
    *,
    role: str,
    status: str,
) -> UUID:
    row = conn.execute(
        "insert into memberships (user_id, org_id, workspace_id, role, status) values (%s, %s, %s, %s, %s)"
        " returning id",
        [user, *scope, role, status],
    ).fetchone()
    assert row is not None
    return row[0]


def _refused(
    conn: psycopg.Connection[Any], exc: type[Exception], sql: str, params: list[Any]
) -> None:
    with pytest.raises(exc), conn.transaction():
        conn.execute(sql, params)  # type: ignore[arg-type]


# --- R-1 criterion 7, Q-23: one live membership per user -------------------------------------------------------

_op = st.one_of(
    st.tuples(st.just("insert"), st.integers(0, 2), st.integers(0, 1)),
    st.tuples(st.just("move"), st.integers(0, 2), st.sampled_from(STATES)),
)


@DB_SETTINGS
@given(st.lists(_op, min_size=1, max_size=14))
def test_property_16_one_live_membership_per_user(
    tx: psycopg.Connection[Any], ops: list[tuple[str, int, Any]]
) -> None:
    """**Validates: Requirements 1.7** (Property 16: no user ever holds two memberships in pending_approval, active
    or suspended, and a user whose membership is removed or rejected can create a new one)."""
    owner = tx
    with owner.transaction(force_rollback=True):
        users = _users(owner, 3)
        org, ws = _org(owner, 2)
        model: dict[int, list[tuple[UUID, str]]] = {i: [] for i in range(3)}
        for kind, u, arg in ops:
            history = model[u]
            if kind == "insert":
                allowed = not any(s in LIVE for _, s in history)
                try:
                    with owner.transaction():
                        mid = _member(
                            owner,
                            users[u],
                            (org, ws[arg]),
                            role="tenant",
                            status="pending_approval",
                        )
                    history.append((mid, "pending_approval"))
                    assert allowed, "second live membership was accepted"
                except psycopg.errors.UniqueViolation:
                    assert not allowed, "a user without a live membership could not onboard"
            elif history:
                mid, current = history[-1]
                allowed = arg == current or (current, arg) in MEMBERSHIP_PAIRS
                try:
                    with owner.transaction():
                        owner.execute(
                            "update memberships set status = %s where id = %s", [arg, mid]
                        )
                    history[-1] = (mid, arg)
                    assert allowed, f"illegal transition {current} -> {arg} was accepted"
                except psycopg.errors.CheckViolation:
                    assert not allowed, f"legal transition {current} -> {arg} was refused"
            live = owner.execute(
                "select max(n) from (select count(*) as n from memberships where user_id = any(%s)"
                " and status = any(%s) group by user_id) c",
                [users, list(LIVE)],
            ).fetchone()
            assert live is not None and (live[0] or 0) <= 1


def test_removed_admin_does_not_block_a_successor_but_a_live_one_does(
    tx: psycopg.Connection[Any],
) -> None:
    old, successor, second = _users(tx, 3)
    org, (ws,) = _org(tx, 1)
    mid = _member(tx, old, (org, ws), role="admin", status="active")
    sql = (
        "insert into memberships (user_id, org_id, workspace_id, role, status)"
        " values (%s, %s, %s, 'admin', 'pending_approval')"
    )
    _refused(tx, psycopg.errors.UniqueViolation, sql, [successor, org, ws])
    tx.execute("update memberships set status = 'removed' where id = %s", [mid])
    _member(
        tx, successor, (org, ws), role="admin", status="pending_approval"
    )  # the 7.8 successor join
    _refused(tx, psycopg.errors.UniqueViolation, sql, [second, org, ws])
    _member(
        tx, old, (org, None), role="super_admin", status="active"
    )  # the removed person can onboard again


def test_membership_status_is_one_of_the_6_2_states(tx: psycopg.Connection[Any]) -> None:
    (u,) = _users(tx, 1)
    org, (ws,) = _org(tx, 1)
    _refused(
        tx,
        psycopg.errors.CheckViolation,
        "insert into memberships (user_id, org_id, workspace_id, role, status)"
        " values (%s, %s, %s, 'tenant', 'pending')",
        [u, org, ws],
    )


def test_approver_is_never_the_member(tx: psycopg.Connection[Any]) -> None:
    member, approver = _users(tx, 2)
    org, (ws,) = _org(tx, 1)
    mid = _member(tx, member, (org, ws), role="tenant", status="pending_approval")
    sql = "update memberships set status = 'active', approver_id = %s where id = %s"
    _refused(tx, psycopg.errors.CheckViolation, sql, [member, mid])
    tx.execute(sql, [approver, mid])


def test_role_is_immutable_even_for_the_owner(tx: psycopg.Connection[Any]) -> None:
    (u,) = _users(tx, 1)
    org, (ws,) = _org(tx, 1)
    mid = _member(tx, u, (org, ws), role="tenant", status="active")
    with pytest.raises(psycopg.errors.CheckViolation) as err, tx.transaction():
        tx.execute("update memberships set role = 'admin' where id = %s", [mid])
    assert err.value.diag.constraint_name == "memberships_role_immutable"
    tx.execute(
        "update memberships set role = 'tenant', status = 'suspended' where id = %s", [mid]
    )  # same role


def test_identity_cannot_update_role_or_scope_columns(database: str) -> None:
    with connect_role(load_settings(), "svc_identity", database=database) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update memberships set role = 'admin' where false")
        conn.rollback()
        for column in ("user_id", "org_id", "workspace_id"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"update memberships set {column} = {column} where false")  # noqa: S608
            conn.rollback()


def test_workspace_goes_pending_provisioning_active(tx: psycopg.Connection[Any]) -> None:
    _, (ws,) = _org(tx, 1, status="pending")
    sql = "update workspaces set status = %s where id = %s"
    _refused(tx, psycopg.errors.CheckViolation, sql, ["active", ws])
    tx.execute(sql, ["provisioning", ws])
    tx.execute(sql, ["active", ws])


# --- R-1 criteria 3 and 4: composite foreign keys --------------------------------------------------------------


def test_every_foreign_key_between_scoped_tables_carries_the_scope(
    tx: psycopg.Connection[Any],
) -> None:
    """Criterion 3: an FK between two workspace tables includes org_id and workspace_id; between two organization
    tables it includes org_id."""
    rows = tx.execute(
        """
        with fk as (
            select c.conname, c.conrelid, c.confrelid,
                   array(select a.attname::text from unnest(c.conkey) k
                         join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k) as cols
            from pg_constraint c where c.contype = 'f'
        ), has as (
            select attrelid, array_agg(attname::text) as names from pg_attribute
            where attname in ('org_id', 'workspace_id') and not attisdropped and attnum > 0 group by attrelid
        )
        select fk.conname, fk.conrelid::regclass::text, fk.cols, fk.confrelid::regclass::text
        from fk join has c on c.attrelid = fk.conrelid join has p on p.attrelid = fk.confrelid
        where (c.names @> array['workspace_id'] and p.names @> array['workspace_id']
               and not fk.cols @> array['org_id', 'workspace_id'])
           or (c.names @> array['org_id'] and p.names @> array['org_id'] and not fk.cols @> array['org_id'])
        """
    ).fetchall()
    assert rows == []


@DB_SETTINGS
@given(
    child=st.sampled_from(["query", "segment"]),
    scope=st.sampled_from(["same", "other_workspace", "other_org", "mixed"]),
    op=st.sampled_from(["insert", "update"]),
)
def test_property_4_cross_scope_references_are_rejected(
    tx: psycopg.Connection[Any], child: str, scope: str, op: str
) -> None:
    """**Validates: Requirements 1.3, 1.4** (Property 4: a reference into another workspace or organization fails
    with a foreign-key violation and both rows stay unchanged)."""
    owner = tx
    with owner.transaction(force_rollback=True):
        (u,) = _users(owner, 1)
        org1, (ws_a, ws_b) = _org(owner, 2)
        org2, (ws_c,) = _org(owner, 1)
        conv = uuid4()
        owner.execute(
            "insert into conversations (id, org_id, workspace_id, user_id, title_ct)"
            " values (%s, %s, %s, %s, '\\x00')",
            [conv, org1, ws_a, u],
        )
        target = {
            "same": (org1, ws_a),
            "other_workspace": (org1, ws_b),
            "other_org": (org2, ws_c),
            "mixed": (org2, ws_a),
        }[scope]
        query_sql = (
            "insert into queries (id, org_id, workspace_id, user_id, conversation_id, question_ct, outcome,"
            " result_ct) values (%s, %s, %s, %s, %s, '\\x00', 'answered', '\\x00')"
        )
        segment_sql = (
            "insert into query_segments (query_id, seq, org_id, workspace_id, user_id, kind, text_sha256, verdict,"
            " audit_event_id) values (%s, 1, %s, %s, %s, 'sentence', 'x', 'pass', 1)"
        )
        parent_q = uuid4()
        owner.execute(query_sql, [parent_q, org1, ws_a, u, conv])
        if child == "query":
            row_id, table, key = uuid4(), "queries", "id"
            first = (query_sql, [row_id, *target, u, conv])
            valid = (query_sql, [row_id, org1, ws_a, u, conv])
        else:
            row_id, table, key = parent_q, "query_segments", "query_id"
            first = (segment_sql, [parent_q, *target, u])
            valid = (segment_sql, [parent_q, org1, ws_a, u])

        def snapshot() -> list[Any]:
            return owner.execute(
                "select (select count(*) from conversations where id = %s),"
                " (select array_agg(q::text order by q.id) from queries q where q.user_id = %s),"
                " (select array_agg(s::text) from query_segments s where s.user_id = %s)",
                [conv, u, u],
            ).fetchall()

        if op == "update":
            owner.execute(*valid)
        before = snapshot()
        try:
            with owner.transaction():
                if op == "insert":
                    owner.execute(*first)
                else:
                    owner.execute(
                        f"update {table} set org_id = %s, workspace_id = %s where {key} = %s",  # noqa: S608
                        [*target, row_id],
                    )
            assert scope == "same", f"{op} into {scope} scope was accepted"
        except psycopg.errors.ForeignKeyViolation:
            assert scope != "same"
            assert snapshot() == before


# --- identity service on the new states ------------------------------------------------------------------------


def test_identity_approval_walks_the_workspace_through_provisioning(database: str) -> None:
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
            mid = c.execute(
                "insert into memberships (user_id, org_id, workspace_id, role, status)"
                " values (%s, %s, %s, 'admin', 'pending_approval') returning id",
                [admin.user_id, org_id, ws],
            ).fetchone()["id"]
            c.execute(
                "insert into memberships (user_id, org_id, workspace_id, role, status)"
                " values (%s, %s, %s, 'tenant', 'pending_approval')",
                [tenant.user_id, org_id, ws],
            )

        admin = svc.resolve(f"test|ad-{tag}", None, None)
        assert admin.membership is not None and admin.membership.status == "pending_approval"
        assert svc.me(admin)["membership"]["status"] == "pending"  # MVP wire name
        out = svc.decide_admin(sa, str(mid), "approve")
        assert out == {"id": str(mid), "status": "active", "workspace_status": "active"}

        tenant = svc.resolve(f"test|tn-{tag}", None, None)
        assert tenant.membership is not None and tenant.membership.status == "pending_approval"
        assert svc.me(tenant)["membership"]["status"] == "pending"
        svc.withdraw(tenant)
        assert svc.resolve(f"test|tn-{tag}", None, None).membership is None  # the request is gone

        with scoped(db.service("identity"), Claims(actor="test")) as c:
            rows = {
                r["role"]: (r["status"], r["approver_id"])
                for r in c.execute(
                    "select role, status, approver_id from memberships where workspace_id = %s",
                    [ws],
                )
            }
            ws_status = c.execute("select status from workspaces where id = %s", [ws]).fetchone()
        assert rows["admin"] == ("active", UUID(sa.user_id))
        assert (
            "tenant" not in rows
        )  # a withdrawal deletes the request: nobody changes their own membership
        assert ws_status is not None and ws_status["status"] == "active"
    finally:
        db.close()
