"""G1.4: PostgreSQL RLS equals the pure-Python oracle of doc section 5.4 on random worlds.

Each *world* is a random organization: membership, workspace and organization states, tiers,
grants (active, expired, future), walls, break-glass and emergency sessions, the private-read
flag, and private and matter documents (some with quarantined chunks). For every user and every
document the test asks PostgreSQL, through the real service roles, and compares with
``lmqa_models.access.decide``. A *scenario* is one (user, document) decision per operation.

Worlds are built by a superuser (BYPASSRLS) so any state can be placed directly; every READ and
WRITE under test goes through the real service roles. Worlds are seeded, so a failure reproduces.
"""

from __future__ import annotations

import os
import random
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest

from lmqa_db.bootstrap import with_database
from lmqa_models import AccessContext, Document, Role, Visibility, decide
from lmqa_testing.pg import role_dsn, superuser_dsn
from lmqa_testing.random_world import (
    World,
    build_world,
    oracle_context,
    oracle_may_upload,
)

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

WORLDS = int(os.environ.get("LMQA_DIFF_WORLDS", "260"))
WRITE_PROBE_EVERY = 4
MIN_SCENARIOS = 20_000


def _set(conn: psycopg.Connection, w: World, user: UUID, role: str) -> None:
    conn.execute(
        "SELECT set_config('app.role', %s, true), set_config('app.org_id', %s, true),"
        " set_config('app.workspace_id', %s, true), set_config('app.user_id', %s, true)",
        (role, str(w.org), str(w.ws), str(user)),
    )


def visible_ids(
    conn: psycopg.Connection, w: World, user: UUID, role: str, table: str, col: str
) -> set[UUID]:
    with conn.transaction(force_rollback=True):
        _set(conn, w, user, role)
        rows = conn.execute(
            f"SELECT {col} FROM {table} WHERE workspace_id = %s", (w.ws,)
        ).fetchall()  # type: ignore[arg-type]
    return {r[0] for r in rows}


def classify(
    conn: psycopg.Connection, w: World, user: UUID, role: str, sql: str, *params: object
) -> str:
    """Run one write probe and say whether it changed a row, matched none, or was refused.

    A DELETE of a document first deletes its chunks in the same transaction, exactly as the
    service does (chunks reference documents), and reports on the document row.
    """
    try:
        with conn.transaction(force_rollback=True):
            _set(conn, w, user, role)
            if sql.startswith("DELETE FROM documents"):
                conn.execute("DELETE FROM chunks WHERE doc_id = %s", params)  # type: ignore[arg-type]
            cur = conn.execute(sql, params)  # type: ignore[arg-type]
            return "applied" if cur.rowcount == 1 else "filtered"
    except psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation:
        return "refused"


def test_g1_4_policies_equal_the_oracle_on_random_worlds(migrated_db: str) -> None:
    dsn = with_database(superuser_dsn(), migrated_db)
    roles = {
        r: psycopg.connect(role_dsn(r, migrated_db))
        for r in ("svc_ingestion", "svc_retrieval", "svc_generation", "svc_validator")
    }
    scenarios = 0
    deciding: Counter[int] = Counter()
    mismatches: list[str] = []
    try:
        with psycopg.connect(dsn, autocommit=True) as admin_conn:
            for index in range(WORLDS):
                now = datetime.now(UTC)
                rng = random.Random(index)
                w = build_world(admin_conn, rng, now)
                everyone = [*w.users(), (w.sa, Role.SUPER_ADMIN)]
                for user, role in everyone:
                    ctx = (
                        oracle_context(w, user, role, now)
                        if role is not Role.SUPER_ADMIN
                        else AccessContext(user_id=user, role=role, now=now)
                    )
                    ctx_role = role.value
                    want_docs = {
                        d.id
                        for d in w.docs
                        if decide(
                            ctx, Document(d.owner, Visibility(d.visibility), d.tier, d.matter)
                        ).allow
                    }
                    for d in w.docs:
                        deciding[
                            decide(
                                ctx, Document(d.owner, Visibility(d.visibility), d.tier, d.matter)
                            ).rule
                        ] += 1
                    # SELECT through four content roles and three content tables.
                    got_docs = visible_ids(
                        roles["svc_ingestion"], w, user, ctx_role, "documents", "id"
                    )
                    if got_docs != want_docs:
                        mismatches.append(
                            f"world {index} {role.value} documents: extra={len(got_docs - want_docs)} missing={len(want_docs - got_docs)}"
                        )
                    want_chunks_all = {d.id for d in w.docs if d.id in want_docs}
                    want_chunks_clean = {
                        d.id for d in w.docs if d.id in want_docs and not d.chunk_quarantined
                    }
                    got_chunks = visible_ids(
                        roles["svc_ingestion"], w, user, ctx_role, "chunks", "doc_id"
                    )
                    if got_chunks != want_chunks_all:
                        mismatches.append(f"world {index} {role.value} chunks(ingestion) differ")
                    for reader in ("svc_retrieval", "svc_generation", "svc_validator"):
                        got = visible_ids(roles[reader], w, user, ctx_role, "chunks", "doc_id")
                        if got != want_chunks_clean:
                            mismatches.append(f"world {index} {role.value} chunks({reader}) differ")
                        got_d = visible_ids(roles[reader], w, user, ctx_role, "documents", "id")
                        if got_d != want_docs:
                            mismatches.append(
                                f"world {index} {role.value} documents({reader}) differ"
                            )
                    scenarios += len(w.docs) * 6
                    if role is Role.SUPER_ADMIN or index % WRITE_PROBE_EVERY:
                        continue
                    # WRITE probes through svc_ingestion: UPDATE and DELETE of each document.
                    actor_active = ctx.membership_active and ctx.workspace_active and ctx.org_active
                    ing = roles["svc_ingestion"]
                    for d in w.docs:
                        readable = d.id in want_docs
                        owner = d.owner == user
                        for verb, sql in (
                            ("update", "UPDATE documents SET failure_reason = 'p' WHERE id = %s"),
                            ("delete", "DELETE FROM documents WHERE id = %s"),
                        ):
                            got = classify(ing, w, user, ctx_role, sql, d.id)
                            if not (readable and owner and actor_active):
                                want = "filtered"
                            elif verb == "update" and not oracle_may_upload(ctx, d.matter, d.tier):
                                want = "refused"
                            else:
                                want = "applied"
                            scenarios += 1
                            if got != want:
                                mismatches.append(
                                    f"world {index} {role.value} {verb} {d.id}: db={got} oracle={want}"
                                )
                    # INSERT probes: owner must be the caller and the upload ceiling must hold.
                    for matter in (None, *w.matters):
                        for tier in (1, 2, 3, 4):
                            sql = (
                                "INSERT INTO documents (org_id, workspace_id, owner_user_id, matter_id,"
                                " title_ciphertext, visibility, confidentiality_tier)"
                                " VALUES (%s, %s, %s, %s, %s, 'private', %s)"
                            )
                            got = classify(
                                ing,
                                w,
                                user,
                                ctx_role,
                                sql,
                                w.org,
                                w.ws,
                                user,
                                matter,
                                os.urandom(8),
                                tier,
                            )
                            want = "applied" if oracle_may_upload(ctx, matter, tier) else "refused"
                            scenarios += 1
                            if got != want:
                                mismatches.append(
                                    f"world {index} {role.value} insert matter={matter} tier={tier}: db={got} oracle={want}"
                                )
                    other = w.tenants[0] if user != w.tenants[0] else w.admin
                    forged = classify(
                        ing,
                        w,
                        user,
                        ctx_role,
                        "INSERT INTO documents (org_id, workspace_id, owner_user_id, title_ciphertext)"
                        " VALUES (%s, %s, %s, %s)",
                        w.org,
                        w.ws,
                        other,
                        os.urandom(8),
                    )
                    scenarios += 1
                    if forged != "refused":
                        mismatches.append(
                            f"world {index} {role.value}: inserting a document owned by someone else was {forged}"
                        )
    finally:
        for conn in roles.values():
            conn.close()
    assert mismatches == [], f"{len(mismatches)} mismatches, first: {mismatches[:5]}"
    assert scenarios >= MIN_SCENARIOS, f"only {scenarios} scenarios ran"
    # The generator must actually exercise every rule, or equality would be vacuous.
    for rule in (1, 2, 3, 4, 5, 6, 7, 8):
        assert deciding[rule] >= 100, (
            f"rule {rule} decided only {deciding[rule]} times: {dict(deciding)}"
        )
