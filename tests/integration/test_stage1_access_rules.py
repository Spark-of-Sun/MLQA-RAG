"""Task 3.4: the access decision is §5.4 rules 1 to 8 only (R-4.1, R-4.5, R-4.6, R-5.3, R-5.4, R-6.2, R-6.4, R-7,
R-8; DEV-14, DEV-15).

One test per rule, a check that SQL `app_can_read` returns exactly what `lmqa_testing.oracle` allows on a small
fixed world (both tables, all three operations), and the upload tier ceiling, the visibility CHECK and the wall
scope bump. Property 1 (at least 20,000 generated worlds, task 3.10) is not here.

The world is written by a superuser inside one transaction that is always rolled back, so the test can also run on
the migrated dev database (LMQA_TEST_DATABASE=lmqa). Reads switch to the runtime role `lmqa_app` with
`SET LOCAL ROLE`, so FORCE RLS and the policies in db/policies decide every row.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from lmqa_db import connect_role
from lmqa_db.migrate import drop_database, migrate
from lmqa_models.settings import load_settings
from lmqa_testing.oracle import OPERATIONS, Document, Principal, World, decide

pytestmark = [pytest.mark.stage1, pytest.mark.integration]

READER = "lmqa_app"
TABLES = ("documents", "chunks")


@pytest.fixture(scope="module")
def database() -> Iterator[str]:
    existing = os.environ.get("LMQA_TEST_DATABASE")
    if existing:
        yield existing
        return
    cfg = load_settings()
    name = f"lmqa_scratch_access_{os.getpid()}"
    try:
        migrate(cfg, name)
    except psycopg.OperationalError as exc:  # pragma: no cover - no Postgres running
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield name
    drop_database(cfg, name)


@dataclass
class Fixture:
    """The same world twice: as rows in PostgreSQL and as an oracle `World`."""

    conn: psycopg.Connection[Any]
    world: World
    users: dict[str, UUID] = field(default_factory=dict)
    principals: dict[str, Principal] = field(default_factory=dict)
    docs: dict[str, Document] = field(default_factory=dict)
    matters: dict[str, UUID] = field(default_factory=dict)
    workspaces: dict[str, tuple[UUID, UUID]] = field(
        default_factory=dict
    )  # name -> (org, workspace)

    def visible(self, who: str, table: str = "documents", op: str = "read") -> set[str]:
        """Names of the documents (or of the documents whose chunk) `who` reads under RLS as `lmqa_app`."""
        column = "id" if table == "documents" else "document_id"
        self.conn.execute(f"set local role {READER}")
        try:
            self.conn.execute(
                "select set_config('app.user_id', %s, true), set_config('app.operation', %s, true)",
                [str(self.users[who]), op],
            )
            rows = self.conn.execute(f"select {column} from {table}").fetchall()  # noqa: S608 - fixed names
        finally:
            self.conn.execute("reset role")
        by_id = {UUID(d.id): name for name, d in self.docs.items()}
        return {by_id[r[0]] for r in rows if r[0] in by_id}

    def oracle(self, who: str, op: str = "read") -> set[str]:
        p = self.principals[who]
        return {name for name, d in self.docs.items() if decide(self.world, p, d, op)[1]}

    def rule(self, who: str, doc: str, op: str = "read") -> tuple[int, bool]:
        return decide(self.world, self.principals[who], self.docs[doc], op)


def _seed(conn: psycopg.Connection[Any]) -> Fixture:  # noqa: PLR0915 - one linear world
    now: datetime = conn.execute("select now()").fetchone()[0]
    f = Fixture(conn, World(now=now))

    def user(name: str) -> UUID:
        uid = uuid4()
        conn.execute("insert into users (id, auth0_sub) values (%s, %s)", [uid, f"test|{uid}"])
        f.users[name] = uid
        return uid

    def org(name: str, kind: str, *, emergency: bool, private_read: bool) -> None:
        o, w = uuid4(), uuid4()
        conn.execute(
            "insert into organizations (id, name, kind, status) values (%s, %s, %s, 'active')",
            [o, f"Org {name}", kind],
        )
        conn.execute(
            "insert into workspaces (id, org_id, name, status, emergency_access, admin_can_read_private)"
            " values (%s, %s, %s, 'active', %s, %s)",
            [w, o, f"Workspace {name}", emergency, private_read],
        )
        f.workspaces[name] = (o, w)
        f.world.emergency_enabled[str(w)] = emergency
        f.world.admin_can_read_private[str(w)] = private_read

    def member(name: str, ws: str, role: str, status: str = "active") -> None:
        o, w = f.workspaces[ws]
        uid = user(name)
        workspace = None if role == "super_admin" else w
        conn.execute(
            "insert into memberships (user_id, org_id, workspace_id, role, status)"
            " values (%s, %s, %s, %s, %s)",
            [uid, o, workspace, role, status],
        )
        kind = conn.execute("select kind from organizations where id = %s", [o]).fetchone()[0]
        f.principals[name] = Principal(
            user_id=str(uid),
            role=role,
            workspace_id=None if workspace is None else str(w),
            membership_active=status == "active",
            workspace_active=True,
            org_active=True,
            org_kind=kind,
        )

    def matter(name: str, ws: str, by: str) -> None:
        o, w = f.workspaces[ws]
        mid = uuid4()
        conn.execute(
            "insert into matters (id, org_id, workspace_id, label, kind, created_by)"
            " values (%s, %s, %s, %s, 'matter', %s)",
            [mid, o, w, f"Matter {name}", f.users[by]],
        )
        f.matters[name] = mid

    def doc(name: str, ws: str, owner: str, tier: int, matter_name: str | None = None) -> None:
        o, w = f.workspaces[ws]
        did, mid = uuid4(), f.matters.get(matter_name or "")
        visibility = "matter" if mid else "private"
        conn.execute(
            "insert into documents (id, org_id, workspace_id, owner_id, title_ct, filename_ct, file_type,"
            " size_bytes, sha256, object_key, visibility, matter_id, tier, status)"
            " values (%s, %s, %s, %s, %s, '\\x00', 'txt', 1, 'x', 'k', %s, %s, %s, 'ready')",
            [did, o, w, f.users[owner], f"Doc {name}".encode(), visibility, mid, tier],
        )
        conn.execute(
            "insert into chunks (org_id, workspace_id, document_id, owner_id, visibility, matter_id, tier,"
            " ordinal, kind, text_ct, text_sha256, token_count)"
            " values (%s, %s, %s, %s, %s, %s, %s, 0, 'paragraph', '\\x00', 'x', 1)",
            [o, w, did, f.users[owner], visibility, mid, tier],
        )
        f.docs[name] = Document(
            id=str(did),
            workspace_id=str(w),
            owner_id=str(f.users[owner]),
            visibility=visibility,
            matter_id=None if mid is None else str(mid),
            tier=tier,
        )

    def grant(who: str, matter_name: str, max_tier: int, by: str, expires: datetime | None) -> None:
        o, w = next(
            v for v in f.workspaces.values() if v[1] == UUID(f.principals[who].workspace_id)
        )
        conn.execute(
            "insert into matter_grants (org_id, workspace_id, matter_id, user_id, max_tier, granted_by,"
            " expires_at) values (%s, %s, %s, %s, %s, %s, %s)",
            [o, w, f.matters[matter_name], f.users[who], max_tier, f.users[by], expires],
        )
        f.world.grants[(str(f.users[who]), str(f.matters[matter_name]))] = (max_tier, expires)

    # Legal workspace L: matter A.
    org("L", "legal", emergency=False, private_read=False)
    member("admin_l", "L", "admin")
    for t in ("t_author", "t_grant", "t_walled", "t_expired", "t_none"):
        member(t, "L", "tenant")
    member("super_l", "L", "super_admin")
    matter("A", "L", by="admin_l")
    grant("t_author", "A", 4, by="admin_l", expires=None)
    doc("a1", "L", "t_author", 1, "A")
    doc("a3", "L", "t_author", 3, "A")
    doc("a_walled_own", "L", "t_walled", 1, "A")
    doc("pl", "L", "t_none", 4)
    grant("t_grant", "A", 2, by="admin_l", expires=now + timedelta(days=1))
    grant("t_walled", "A", 4, by="admin_l", expires=None)
    grant("t_expired", "A", 4, by="admin_l", expires=now - timedelta(hours=1))
    o, w = f.workspaces["L"]
    conn.execute(
        "insert into matter_walls (org_id, workspace_id, matter_id, user_id, reason_code, created_by)"
        " values (%s, %s, %s, %s, 'conflict_of_interest', %s)",
        [o, w, f.matters["A"], f.users["t_walled"], f.users["admin_l"]],
    )
    f.world.walls.add((str(f.users["t_walled"]), str(f.matters["A"])))

    # Medical workspace M: emergency access and admin_can_read_private on; patient matter P.
    org("M", "medical", emergency=True, private_read=True)
    member("admin_m", "M", "admin")
    member("t_emerg", "M", "tenant")
    member("t_m", "M", "tenant")
    member("t_author_m", "M", "tenant")
    member("t_susp", "M", "tenant", status="suspended")
    matter("P", "M", by="admin_m")
    grant("t_author_m", "P", 4, by="admin_m", expires=None)
    doc("p3", "M", "t_author_m", 3, "P")
    doc("p4", "M", "t_author_m", 4, "P")
    doc("pm", "M", "t_m", 2)
    doc("ps", "M", "t_susp", 1)
    o, w = f.workspaces["M"]
    expires = now + timedelta(minutes=30)
    conn.execute(
        "insert into access_exceptions (org_id, workspace_id, matter_id, user_id, reason_code, tier_cap,"
        " expires_at, review_due_at) values (%s, %s, %s, %s, 'treatment_emergency', 3, %s, %s)",
        [o, w, f.matters["P"], f.users["t_emerg"], expires, now + timedelta(hours=72)],
    )
    f.world.emergency[(str(f.users["t_emerg"]), str(f.matters["P"]))] = (3, expires)
    conn.execute(
        "insert into break_glass_sessions (org_id, workspace_id, admin_user_id, reason, step_up_at, expires_at)"
        " values (%s, %s, %s, 'incident review for test', now(), %s)",
        [o, w, f.users["admin_m"], expires],
    )
    f.world.break_glass[str(f.users["admin_m"])] = expires
    return f


@pytest.fixture
def fx(database: str) -> Iterator[Fixture]:
    with (
        connect_role(load_settings(), "postgres", database=database) as conn,
        conn.transaction(force_rollback=True),
    ):
        yield _seed(conn)


def _check(fx: Fixture, who: str, doc: str, expect: tuple[int, bool], op: str = "read") -> None:
    """The oracle returns `expect` (deciding rule, allow), and RLS agrees with its answer on both tables."""
    assert fx.rule(who, doc, op) == expect
    allow = expect[1]
    for table in TABLES:
        assert (doc in fx.visible(who, table, op)) is allow, (who, doc, op, table)


def test_rule_1_inactive_membership_super_admin_and_other_workspace_are_denied(fx: Fixture) -> None:
    _check(fx, "t_susp", "ps", (1, False))  # own document, suspended membership
    _check(fx, "admin_l", "p3", (1, False))  # another workspace
    assert fx.visible("super_l") == set()  # R-4.6: no content rows for the Super Admin
    assert fx.visible("super_l", "chunks") == set()


def test_rule_2_a_wall_beats_ownership_and_grants(fx: Fixture) -> None:
    _check(fx, "t_walled", "a_walled_own", (2, False))
    _check(fx, "t_walled", "a1", (2, False))  # grant at tier 4 does not help


def test_rule_3_owner_reads_own_private_document(fx: Fixture) -> None:
    _check(fx, "t_none", "pl", (3, True))
    _check(fx, "t_none", "pl", (3, True), op="export")


def test_rule_4_admin_reads_matter_documents_at_all_tiers(fx: Fixture) -> None:
    _check(fx, "admin_l", "a3", (4, True))
    _check(fx, "admin_m", "p4", (4, True))


def test_rule_5_unexpired_grant_up_to_max_tier(fx: Fixture) -> None:
    _check(fx, "t_grant", "a1", (5, True))
    _check(fx, "t_grant", "a3", (8, False))  # above max_tier 2
    _check(fx, "t_expired", "a1", (8, False))  # expired grant


def test_rule_6_emergency_exception_read_and_query_only_never_tier_4(fx: Fixture) -> None:
    _check(fx, "t_emerg", "p3", (6, True))
    _check(fx, "t_emerg", "p3", (6, True), op="query")
    _check(fx, "t_emerg", "p3", (6, False), op="export")
    _check(fx, "t_emerg", "p4", (8, False))  # R-5.4


def test_rule_7_break_glass_reads_private_documents_read_and_query_only(fx: Fixture) -> None:
    _check(fx, "admin_m", "pm", (7, True))
    _check(fx, "admin_m", "pm", (7, False), op="export")
    _check(fx, "admin_l", "pl", (8, False))  # no flag and no session in L


def test_rule_8_everything_else_is_denied(fx: Fixture) -> None:
    _check(fx, "t_none", "a1", (8, False))  # no grant
    _check(fx, "t_grant", "pl", (8, False))  # another tenant's private document
    _check(fx, "t_m", "p3", (8, False))  # no grant, no exception


def test_unknown_operation_is_denied(fx: Fixture) -> None:
    assert fx.visible("t_none", op="delete") == set()


def test_sql_app_can_read_equals_the_oracle_on_the_fixed_world(fx: Fixture) -> None:
    for who in fx.principals:
        for op in OPERATIONS:
            expected = fx.oracle(who, op)
            for table in TABLES:
                assert fx.visible(who, table, op) == expected, (who, op, table)


def test_rules_7a_and_7b_are_gone(fx: Fixture) -> None:
    """A share row grants nothing, and the database refuses `workspace` visibility (DEV-14)."""
    o, w = fx.workspaces["L"]
    fx.conn.execute(
        "insert into document_shares (org_id, workspace_id, document_id, owner_id, user_id)"
        " values (%s, %s, %s, %s, %s)",
        [o, w, UUID(fx.docs["pl"].id), fx.users["t_none"], fx.users["t_grant"]],
    )
    assert "pl" not in fx.visible("t_grant")
    with pytest.raises(psycopg.errors.CheckViolation), fx.conn.transaction():
        fx.conn.execute(
            "update documents set visibility = 'workspace' where id = %s", [UUID(fx.docs["pl"].id)]
        )
    body = fx.conn.execute(
        "select pg_get_functiondef('app_can_read(uuid, uuid, text, uuid, smallint, uuid)'::regprocedure)"
    ).fetchone()[0]
    assert "document_shares" not in body
    assert "'workspace'" not in body


def _upload(fx: Fixture, who: str, ws: str, tier: int, matter_name: str | None = None) -> bool:
    """Insert a document as `who` under RLS; True when the policy accepts it."""
    o, w = fx.workspaces[ws]
    mid = fx.matters.get(matter_name or "")
    try:
        with fx.conn.transaction():
            fx.conn.execute(f"set local role {READER}")
            fx.conn.execute("select set_config('app.user_id', %s, true)", [str(fx.users[who])])
            fx.conn.execute(
                "insert into documents (org_id, workspace_id, owner_id, title_ct, filename_ct, file_type,"
                " size_bytes, sha256, object_key, visibility, matter_id, tier)"
                " values (%s, %s, %s, '\\x00', '\\x00', 'txt', 1, 'x', 'k', %s, %s, %s)",
                [o, w, fx.users[who], "matter" if mid else "private", mid, tier],
            )
            fx.conn.execute("reset role")
    except psycopg.errors.InsufficientPrivilege:
        fx.conn.execute("reset role")
        return False
    return True


def test_upload_tier_ceiling(fx: Fixture) -> None:
    """R-5.3: admin on a matter and anyone on a private document may use tier 4; a tenant is capped by the grant."""
    assert _upload(fx, "admin_l", "L", 4, "A")
    assert _upload(fx, "t_none", "L", 4)
    assert _upload(fx, "t_grant", "L", 2, "A")
    assert not _upload(fx, "t_grant", "L", 3, "A")
    assert not _upload(fx, "t_none", "L", 1, "A")  # no grant
    assert not _upload(fx, "t_expired", "L", 1, "A")  # expired grant
    assert not _upload(fx, "t_walled", "L", 1, "A")  # walled
    assert not _upload(fx, "t_emerg", "M", 1, "P")  # an emergency exception never allows an upload


def test_a_wall_bumps_scope_version_and_scope_hash_in_principal_v(fx: Fixture) -> None:
    """R-6.4: creating a wall changes the walled user's scope hash at once and the next read is denied."""
    uid = fx.users["t_grant"]
    query = "select scope_version, scope_hash from principal_v where user_id = %s"
    before = fx.conn.execute(query, [uid]).fetchone()
    o, w = fx.workspaces["L"]
    fx.conn.execute(
        "insert into matter_walls (org_id, workspace_id, matter_id, user_id, reason_code, created_by)"
        " values (%s, %s, %s, %s, 'lateral_hire', %s)",
        [o, w, fx.matters["A"], uid, fx.users["admin_l"]],
    )
    after = fx.conn.execute(query, [uid]).fetchone()
    assert after[0] == before[0] + 1
    assert after[1] != before[1]
    assert after[1]  # a real digest, not the empty default
    assert "a1" not in fx.visible("t_grant")
