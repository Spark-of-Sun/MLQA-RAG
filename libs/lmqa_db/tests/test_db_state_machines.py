"""G1.9: the database enforces every lifecycle declared in contracts/state-machines.yaml.

For each machine every ordered pair of states is attempted against the real trigger: declared
pairs must succeed and every other pair must be refused (SQLSTATE 23514). Rows are inserted
directly in an arbitrary starting state by a superuser, because inserts are not guarded (a
machine's *initial* state is a service rule) and the point is to test the UPDATE trigger.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from lmqa_db.bootstrap import with_database
from lmqa_models import StateMachine, load_machines
from lmqa_testing import world
from lmqa_testing.pg import superuser_dsn

if TYPE_CHECKING:
    from collections.abc import Callable

    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

MACHINES = load_machines()


class Base:
    """The org, workspace and users every inserted row hangs off."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.org = self._one(
            "INSERT INTO orgs (name, deployment_type, state) VALUES ('sm', 'legal', 'active') RETURNING id"
        )
        self.ws = self._one(
            "INSERT INTO workspaces (org_id, state) VALUES (%s, 'active') RETURNING id", self.org
        )
        self.user = self.new_user()

    def _one(self, sql: str, *params: object) -> UUID:
        row = self.conn.execute(sql, params).fetchone()  # type: ignore[arg-type]
        assert row is not None
        return row[0]

    def new_user(self) -> UUID:
        sub = f"auth0|{uuid4().hex}"
        return self._one("INSERT INTO users (auth0_sub) VALUES (%s) RETURNING id", sub)

    def insert(self, name: str, state: str) -> UUID:
        factories: dict[str, Callable[[str], UUID]] = {
            "organization": lambda st: self._one(
                "INSERT INTO orgs (name, deployment_type, state) VALUES ('x', 'legal', %s) RETURNING id",
                st,
            ),
            "workspace": lambda st: self._one(
                "INSERT INTO workspaces (org_id, state) VALUES (%s, %s) RETURNING id", self.org, st
            ),
            "membership": lambda st: self._one(
                "INSERT INTO memberships (user_id, org_id, workspace_id, role, state)"
                " VALUES (%s, %s, %s, 'tenant', %s) RETURNING id",
                self.new_user(),
                self.org,
                self.ws,
                st,
            ),
            "document": lambda st: self._one(
                "INSERT INTO documents (org_id, workspace_id, owner_user_id, title_ciphertext, status)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                self.org,
                self.ws,
                self.user,
                os.urandom(8),
                st,
            ),
            "join_code": lambda st: self._one(
                "INSERT INTO join_codes (kind, org_id, workspace_id, lookup_id, code_hash, pepper_id,"
                " expires_at, max_uses, state) VALUES ('admin', %s, %s, %s, %s, 'v1',"
                " now() + interval '1 day', 5, %s) RETURNING id",
                self.org,
                self.ws,
                uuid4().hex[:8],
                os.urandom(8),
                st,
            ),
            "governance_request": lambda st: self._one(
                "INSERT INTO governance_requests (org_id, kind, initiator_id, expires_at, state)"
                " VALUES (%s, 'org_delete', %s, now() + interval '1 day', %s) RETURNING id",
                self.org,
                self.user,
                st,
            ),
            "access_session": lambda st: self._one(
                "INSERT INTO access_sessions (org_id, workspace_id, user_id, kind, reason_code, expires_at, state)"
                " VALUES (%s, %s, %s, 'break_glass', 'x', now() + interval '1 hour', %s) RETURNING id",
                self.org,
                self.ws,
                self.user,
                st,
            ),
        }
        return factories[name](state)


def _state(conn: psycopg.Connection, machine: StateMachine, row_id: UUID) -> str:
    row = conn.execute(
        f"SELECT {machine.column}::text FROM {machine.table} WHERE id = %s",  # type: ignore[arg-type]
        (row_id,),
    ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.parametrize("name", sorted(MACHINES))
def test_every_state_pair_is_enforced_by_the_database(migrated_db: str, name: str) -> None:
    machine = MACHINES[name]
    legal = {(t.from_state, t.to_state) for t in machine.transitions}
    mistakes: list[str] = []
    with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as conn:
        base = Base(conn)
        for start in machine.states:
            for end in machine.states:
                if start == end:
                    continue
                row_id = base.insert(name, start)
                try:
                    with conn.transaction():
                        conn.execute(
                            f"UPDATE {machine.table} SET {machine.column} = %s WHERE id = %s",  # type: ignore[arg-type]
                            (end, row_id),
                        )
                    ok = True
                except psycopg.errors.CheckViolation as exc:
                    ok = False
                    if "illegal" not in str(exc):
                        mistakes.append(f"{start}->{end}: unexpected check violation {exc}")
                if ok != ((start, end) in legal):
                    mistakes.append(f"{start}->{end}: database said {'allow' if ok else 'refuse'}")
                expected_state = end if ok else start
                if _state(conn, machine, row_id) != expected_state:
                    mistakes.append(f"{start}->{end}: row ended in the wrong state")
    assert mistakes == []


@pytest.mark.parametrize("name", sorted(MACHINES))
def test_database_transition_table_equals_the_yaml(migrated_db: str, name: str) -> None:
    machine = MACHINES[name]
    with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as conn:
        rows = conn.execute(f"SELECT from_state, to_state FROM sm_{name}_transitions").fetchall()  # type: ignore[arg-type]
    assert set(rows) == {(t.from_state, t.to_state) for t in machine.transitions}


@pytest.mark.asyncio
async def test_a_service_role_cannot_skip_a_state(stack: Stack) -> None:
    """The guard is SECURITY DEFINER, so it works for a role with no grant on the sm_ table."""
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, ws)  # pending_approval -> active, a legal transition
    for illegal in ("pending_approval", "rejected"):
        with pytest.raises(DBAPIError, match="illegal membership transition"):
            async with stack.identity.scoped(world.SYSTEM) as s:
                await s.execute(
                    text("UPDATE memberships SET state = :s WHERE user_id = :u"),
                    {"s": illegal, "u": tenant},
                )
    async with stack.identity.scoped(world.SYSTEM) as s:
        await s.execute(
            text("UPDATE memberships SET state = 'suspended' WHERE user_id = :u"), {"u": tenant}
        )
        version = (
            await s.execute(
                text("SELECT principal_version FROM memberships WHERE user_id = :u"), {"u": tenant}
            )
        ).scalar_one()
    assert version == 3, "pending->active and active->suspended each bump principal_version"
