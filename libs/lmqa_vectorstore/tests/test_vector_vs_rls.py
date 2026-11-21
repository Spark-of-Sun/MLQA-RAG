"""G5.1 (read-only key) and G5.4 (vector filter vs PostgreSQL RLS), on real Qdrant and PostgreSQL.

For random worlds, every chunk is indexed in Qdrant and every user is searched with the filter
built from their scope. The Qdrant result must CONTAIN everything PostgreSQL RLS lets them read
(the vector store is never narrower than the authority) and must EQUAL it when the actor is active
(the filter is exact). Vectors here are constant filler: they are not text, and the point of the
test is the filter. A negative control proves the comparison can fail.
"""

from __future__ import annotations

import os
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from qdrant_client.http.exceptions import UnexpectedResponse

from lmqa_db.bootstrap import with_database
from lmqa_testing.pg import role_dsn, superuser_dsn
from lmqa_testing.random_world import World, build_world, oracle_context
from lmqa_vectorstore import ChunkPoint, SparseVec, VectorReader, VectorScope, VectorWriter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from lmqa_models import Role

pytestmark = [pytest.mark.integration, pytest.mark.stage5]
URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
RW = os.environ.get("QDRANT_KEY_RW", "lmqa-dev-rw-key")
RO = os.environ.get("QDRANT_KEY_RO", "lmqa-dev-ro-key")
DIM = 8
WORLDS = int(os.environ.get("LMQA_VECTOR_WORLDS", "60"))
QUERY = [1.0] * DIM
SPARSE = SparseVec([1, 2, 3], [1.0, 1.0, 1.0])


@pytest_asyncio.fixture
async def collection() -> AsyncGenerator[tuple[str, VectorWriter, VectorReader]]:
    name = f"lmqa_test_{uuid4().hex[:10]}"
    writer, reader = VectorWriter(URL, RW, name), VectorReader(URL, RO, name)
    await writer.ensure_collection(DIM)
    yield name, writer, reader
    await writer.drop_collection()
    await writer.aclose()
    await reader.aclose()


def _scope(
    w: World, user: UUID, role: Role, now: datetime, *, ignore_walls: bool = False
) -> VectorScope:
    ctx = oracle_context(w, user, role, now)
    return VectorScope(
        org_id=w.org,
        workspace_id=w.ws,
        user_id=user,
        role=role.value,
        grants={m: g.max_tier for m, g in ctx.grants.items() if g.is_active(now)},
        walled=frozenset() if ignore_walls else ctx.walls,
        emergency_matters=frozenset(m for m, exp in ctx.emergency.items() if exp > now),
        admin_private_read=ctx.admin_can_read_private and ctx.break_glass_active,
    )


def _rls_chunk_ids(conn: psycopg.Connection, w: World, user: UUID, role: str) -> set[UUID]:
    with conn.transaction(force_rollback=True):
        conn.execute(
            "SELECT set_config('app.role', %s, true), set_config('app.org_id', %s, true),"
            " set_config('app.workspace_id', %s, true), set_config('app.user_id', %s, true)",
            (role, str(w.org), str(w.ws), str(user)),
        )
        return {
            r[0]
            for r in conn.execute(
                "SELECT id FROM chunks WHERE workspace_id = %s", (w.ws,)
            ).fetchall()
        }


@pytest.mark.asyncio
async def test_g5_4_vector_filter_contains_rls_and_equals_it_for_active_actors(
    migrated_db: str, collection: tuple[str, VectorWriter, VectorReader]
) -> None:
    _name, writer, reader = collection
    compared = nonempty = weaker_filter_differs = 0
    retrieval = psycopg.connect(role_dsn("svc_retrieval", migrated_db))
    try:
        with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as admin:
            for index in range(WORLDS):
                now = datetime.now(UTC)
                w = build_world(admin, random.Random(10_000 + index), now)
                rows = admin.execute(
                    "SELECT id, doc_id, owner_user_id, matter_id, visibility, confidentiality_tier, quarantined"
                    " FROM chunks WHERE workspace_id = %s",
                    (w.ws,),
                ).fetchall()
                # Quarantined chunks are never embedded (doc 11.1).
                await writer.upsert(
                    [
                        ChunkPoint(
                            r[0], [1.0] * DIM, SPARSE, w.org, w.ws, r[1], 1, r[2], r[3], r[4], r[5]
                        )
                        for r in rows
                        if not r[6]
                    ]
                )
                for user, role in w.users():
                    scope = _scope(w, user, role, now)
                    hits, overfetch = await reader.search(scope, QUERY, SPARSE, limit=500)
                    got = {h.chunk_id for h in hits}
                    want = _rls_chunk_ids(retrieval, w, user, role.value)
                    assert not overfetch
                    assert want <= got, (
                        f"world {index} {role.value}: Qdrant missed {len(want - got)} readable chunks"
                    )
                    ctx = oracle_context(w, user, role, now)
                    if ctx.membership_active and ctx.workspace_active and ctx.org_active:
                        assert got == want, (
                            f"world {index} {role.value}: filter is not exact (+{len(got - want)})"
                        )
                    compared += 1
                    nonempty += bool(want)
                    # Negative control: dropping the walls from the scope must change some result.
                    if ctx.walls:
                        hits2, _ = await reader.search(
                            _scope(w, user, role, now, ignore_walls=True), QUERY, SPARSE, 500
                        )
                        weaker_filter_differs += {h.chunk_id for h in hits2} != got
    finally:
        retrieval.close()
    assert compared >= 200
    assert nonempty >= 100, "most principals must actually read something, or equality is vacuous"
    assert weaker_filter_differs >= 5, "the comparison is able to detect a missing wall"


@pytest.mark.asyncio
async def test_cross_workspace_and_cross_org_searches_return_nothing_foreign(
    collection: tuple[str, VectorWriter, VectorReader],
) -> None:
    _name, writer, reader = collection
    orgs = [(uuid4(), uuid4(), uuid4()) for _ in range(2)]  # (org, workspace, user)
    chunks = {}
    for org, ws, user in orgs:
        cid = uuid4()
        chunks[org] = cid
        await writer.upsert(
            [ChunkPoint(cid, [1.0] * DIM, SPARSE, org, ws, uuid4(), 1, user, None, "private", 1)]
        )
    for org, ws, user in orgs:
        hits, _ = await reader.search(VectorScope(org, ws, user, "tenant"), QUERY, SPARSE, 50)
        assert {h.chunk_id for h in hits} == {chunks[org]}
        # Right user, wrong workspace: the same private point is not reachable.
        none, _ = await reader.search(VectorScope(org, uuid4(), user, "tenant"), QUERY, SPARSE, 50)
        assert none == []
        other, _ = await reader.search(VectorScope(uuid4(), ws, user, "tenant"), QUERY, SPARSE, 50)
        assert other == []


@pytest.mark.asyncio
async def test_g5_1_the_read_only_key_cannot_write_or_delete(
    collection: tuple[str, VectorWriter, VectorReader],
) -> None:
    name, writer, _reader = collection
    org, ws, user, doc = uuid4(), uuid4(), uuid4(), uuid4()
    point = ChunkPoint(uuid4(), [1.0] * DIM, SPARSE, org, ws, doc, 1, user, None, "private", 1)
    await writer.upsert([point])
    attacker = VectorWriter(URL, RO, name)  # a writer wired with the retrieval (read-only) key
    try:
        for attempt in (
            attacker.upsert([point]),
            attacker.delete_document(org, ws, doc),
            attacker.set_access_payload(org, ws, doc, {"visibility": "matter"}),
            attacker.delete_workspace(org, ws),
        ):
            with pytest.raises(UnexpectedResponse) as err:
                await attempt
            assert err.value.status_code == 403
    finally:
        await attacker.aclose()
    assert await writer.list_points(org, ws) == {point.chunk_id: 1}, "nothing was changed"


@pytest.mark.asyncio
async def test_a_wrong_api_key_is_refused(
    collection: tuple[str, VectorWriter, VectorReader],
) -> None:
    name, _writer, _reader = collection
    nobody = VectorReader(URL, "not-a-key", name)
    try:
        with pytest.raises(UnexpectedResponse):
            await nobody.search(VectorScope(uuid4(), uuid4(), uuid4(), "tenant"), QUERY, SPARSE, 5)
    finally:
        await nobody.aclose()


@pytest.mark.asyncio
async def test_access_payload_updates_are_scoped_and_reject_text_fields(
    collection: tuple[str, VectorWriter, VectorReader],
) -> None:
    _name, writer, reader = collection
    org, ws, owner, doc = uuid4(), uuid4(), uuid4(), uuid4()
    other_org, other_ws = uuid4(), uuid4()
    mine = ChunkPoint(uuid4(), [1.0] * DIM, SPARSE, org, ws, doc, 1, owner, None, "private", 1)
    foreign = ChunkPoint(
        uuid4(), [1.0] * DIM, SPARSE, other_org, other_ws, doc, 1, owner, None, "private", 1
    )
    await writer.upsert([mine, foreign])  # the same doc_id exists in two workspaces
    matter = uuid4()
    await writer.set_access_payload(
        org, ws, doc, {"visibility": "matter", "matter_id": str(matter), "tier": 2}
    )
    reader_scope = VectorScope(org, ws, uuid4(), "tenant", grants={matter: 2})
    hits, _ = await reader.search(reader_scope, QUERY, SPARSE, 10)
    assert [h.chunk_id for h in hits] == [mine.chunk_id], (
        "the update reached only the pinned workspace"
    )
    foreign_hits, _ = await reader.search(
        VectorScope(other_org, other_ws, owner, "tenant"), QUERY, SPARSE, 10
    )
    assert [h.chunk_id for h in foreign_hits] == [foreign.chunk_id], (
        "the other workspace's point is untouched"
    )
    with pytest.raises(ValueError, match="non-access"):
        await writer.set_access_payload(org, ws, doc, {"text": "leak"})
    await writer.delete_document(org, ws, doc)
    assert await writer.list_points(org, ws) == {}
    assert len(await writer.list_points(other_org, other_ws)) == 1


@pytest.mark.asyncio
async def test_g5_8_stale_payload_after_narrowing_still_returns_the_id_so_postgres_must_decide(
    collection: tuple[str, VectorWriter, VectorReader],
) -> None:
    """Index lag is safe only because retrieval cross-checks IDs against PostgreSQL (doc 10.6)."""
    _name, writer, reader = collection
    org, ws, owner, doc, matter = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    tenant = uuid4()
    point = ChunkPoint(uuid4(), [1.0] * DIM, SPARSE, org, ws, doc, 1, owner, matter, "matter", 1)
    await writer.upsert([point])
    scope = VectorScope(org, ws, tenant, "tenant", grants={matter: 4})
    assert [h.chunk_id for h in (await reader.search(scope, QUERY, SPARSE, 5))[0]] == [
        point.chunk_id
    ]
    # Postgres narrows the document to private; until the outbox indexer runs the payload is stale,
    # so the vector store still returns the ID. The cross-check in retrieval drops it.
    assert [h.chunk_id for h in (await reader.search(scope, QUERY, SPARSE, 5))[0]] == [
        point.chunk_id
    ]
    await writer.set_access_payload(org, ws, doc, {"visibility": "private"})
    assert (await reader.search(scope, QUERY, SPARSE, 5))[0] == [], "once re-indexed it is gone"
