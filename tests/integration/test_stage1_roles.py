"""Task 3.1: role model, Super Admin policy set and `scoped(pool, claims)` (R-3.3, R-29.2, R-32.2/3/6, R-79).

The DB tests build their own scratch database with `lmqa_db.migrate.migrate` and drop it afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from hypothesis import given
from hypothesis import strategies as st

from lmqa_db import Claims, Database, MissingContextError, connect_role, scoped
from lmqa_db.migrate import drop_database, migrate
from lmqa_models.settings import DB_SERVICE_ROLES, load_settings

RUNTIME_ROLES = ("lmqa_app", *DB_SERVICE_ROLES)


@pytest.mark.stage1
@pytest.mark.unit
def test_scoped_refuses_without_claims() -> None:
    with pytest.raises(MissingContextError):
        Claims.of(None)
    with pytest.raises(MissingContextError):
        Claims().settings()


@pytest.mark.stage1
@pytest.mark.unit
@given(st.text(min_size=1, max_size=12))
def test_claims_setting_names_are_validated(name: str) -> None:
    """Only `[a-z][a-z0-9_]*` names reach set_config; anything else is refused before any SQL runs."""
    claims = Claims(actor="t", extra={name: "v"})
    ok = (
        name[0].isascii()
        and name[0].islower()
        and all(c.isascii() and (c.islower() or c.isdigit() or c == "_") for c in name)
    )
    if ok:
        assert claims.settings()[name] == "v"
    else:
        with pytest.raises(ValueError, match="invalid context setting"):
            claims.settings()


@pytest.fixture(scope="module")
def scratch() -> Iterator[str]:
    settings = load_settings()
    name = f"lmqa_scratch_roles_{os.getpid()}"
    try:
        migrate(settings, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(settings, name)


@pytest.mark.stage1
@pytest.mark.integration
def test_runtime_roles_are_nobypassrls_non_owners(scratch: str) -> None:
    with connect_role(load_settings(), "lmqa_owner", database=scratch) as conn:
        rows = conn.execute(
            "select r.rolname, r.rolbypassrls, r.rolcanlogin,"
            " exists (select 1 from pg_class c where c.relowner = r.oid) as owns"
            " from pg_roles r where r.rolname = any(%s)",
            [[*RUNTIME_ROLES, "policy_helper", "lmqa_system"]],
        ).fetchall()
        problems = conn.execute("select problem from app_boot_self_test()").fetchall()
        helpers = conn.execute(
            "select p.proname, pg_get_userbyid(p.proowner) from pg_proc p"
            " where p.proname like 'app\\_%%' and p.prosecdef and p.provolatile = 's'"
            " and p.proname <> 'app_boot_self_test'"
        ).fetchall()
    by_role = {r[0]: r for r in rows}
    assert set(RUNTIME_ROLES) <= set(by_role)
    for role in RUNTIME_ROLES:
        _, bypass, login, owns = by_role[role]
        assert login and not bypass and not owns, role
    assert not by_role["policy_helper"][2]  # NOLOGIN
    if "lmqa_system" in by_role:
        assert not by_role["lmqa_system"][1] and not by_role["lmqa_system"][2]
    assert problems == []
    assert helpers and all(owner == "policy_helper" for _, owner in helpers)


@pytest.mark.stage1
@pytest.mark.integration
def test_super_admin_reaches_only_the_5_3_set(scratch: str) -> None:
    db = Database(load_settings(), database=scratch, services=("identity",))
    db.open()
    try:
        idp = db.service("identity")
        org, sa, admin, tenant = uuid4(), uuid4(), uuid4(), uuid4()
        with scoped(idp, Claims(actor="test")) as c:
            for u in (sa, admin, tenant):
                c.execute(
                    "insert into users (id, auth0_sub, email_ct) values (%s, %s, %s)",
                    [u, str(u), f"{u}@x.test".encode()],  # placeholder bytes: nothing here decrypts
                )
            c.execute(
                "insert into organizations (id, name, kind, created_by) values (%s, 'Org One', 'legal', %s)",
                [org, sa],
            )
            ws = c.execute(
                "insert into workspaces (org_id, name) values (%s, 'Workspace One') returning id",
                [org],
            ).fetchone()["id"]
            c.execute(
                "insert into memberships (user_id, org_id, workspace_id, role, status) values"
                " (%s, %s, null, 'super_admin', 'active'), (%s, %s, %s, 'admin', 'active'),"
                " (%s, %s, %s, 'tenant', 'active')",
                [sa, org, admin, org, ws, tenant, org, ws],
            )
        with scoped(idp, Claims(user_id=sa)) as c:
            roles = sorted(r["role"] for r in c.execute("select role from memberships"))
            users = {r["id"] for r in c.execute("select id from users")}
        assert roles == ["admin", "super_admin"]  # no tenant membership rows (R-3.3, R-3.4)
        assert users == {sa, admin}
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            scoped(idp, Claims(user_id=sa)) as c,
        ):
            c.execute("select 1 from documents")  # identity holds no content grant at all
    finally:
        db.close()
