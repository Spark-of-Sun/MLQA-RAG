"""Stage 5 on the real stack: scoped hybrid retrieval that cannot leak, with PostgreSQL as authority."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from lmqa_db import ContextRole, Database
from lmqa_testing import world
from lmqa_testing.corpus import load_corpus
from lmqa_testing.pg import role_dsn
from lmqa_vectorstore import VectorReader
from retrieval.search import NoAccessError, RetrievalUnavailableError, Retriever

if TYPE_CHECKING:
    from .conftest import Env

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_kms,
    pytest.mark.live_models,
    pytest.mark.stage5,
]


async def ingest(env: Env, item, ctx, **kw):
    upload = await env.pipeline.create_upload(
        ctx, item.title, kw.get("visibility", "private"), kw.get("matter"), kw.get("tier", 1)
    )
    await env.components.objects.put_quarantine(
        ctx.org_id, ctx.workspace_id, upload.doc_id, item.data
    )
    result = await env.pipeline.complete_upload(
        ctx, upload.doc_id, item.format, hashlib.sha256(item.data).hexdigest()
    )
    assert result.status == "indexed"
    return upload.doc_id, result


def admin_ctx(env: Env):
    return world.ctx(ContextRole.ADMIN, env.ws.org, env.ws.id, env.ws.admin)


@pytest.mark.asyncio
async def test_an_owner_finds_their_own_document_by_its_content(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="contract")[2]
    doc_id, result = await ingest(env, item, env.owner)
    async with env.components.db.scoped(env.owner) as s:
        headed = (
            await s.execute(
                text(
                    "SELECT heading, ordinal FROM chunks WHERE doc_id = :d AND heading IS NOT NULL"
                    " ORDER BY ordinal"
                ),
                {"d": doc_id},
            )
        ).all()
    assert headed
    found = 0
    for heading, _ordinal in headed[:4]:
        out = await retriever.retrieve(
            env.owner, f"What does the section titled {heading} provide?"
        )
        found += any(c.heading == heading for c in out.chunks[:5])
        assert all(c.doc_id == doc_id for c in out.chunks)
    assert found >= 2, "a smoke check that hybrid retrieval surfaces the named section"
    assert result.chunks > 0


@pytest.mark.asyncio
async def test_g5_4_a_workspace_never_sees_another_workspaces_chunks(
    env: Env, retriever: Retriever
) -> None:
    contract, case = load_corpus(kind="contract")[2], load_corpus(kind="case_report")[2]
    doc_a, _ = await ingest(env, contract, env.owner)
    _ws2, ctx2 = await env.second_workspace()
    doc_b, _ = await ingest(env, case, ctx2)
    async with env.components.db.scoped(env.owner) as s:
        a_ids = {
            str(r[0])
            for r in (
                await s.execute(text("SELECT id FROM chunks WHERE doc_id = :d"), {"d": doc_a})
            ).all()
        }
        a_hashes = {
            r[0]
            for r in (
                await s.execute(
                    text("SELECT text_sha256 FROM chunks WHERE doc_id = :d"), {"d": doc_a}
                )
            ).all()
        }
    for question in (
        "What are the terms of this agreement?",
        "Describe the patient presentation.",
        "indemnification",
    ):
        out = await retriever.retrieve(ctx2, question)
        blob = json.dumps(
            [
                {**c.__dict__, "chunk_id": str(c.chunk_id), "doc_id": str(c.doc_id)}
                for c in out.chunks
            ]
            + out.dropped,
            default=str,
        )
        assert not any(i in blob for i in a_ids | {str(doc_a)}), (
            "no foreign chunk or document ID in any output"
        )
        assert not any(h in blob for h in a_hashes), "no foreign content hash in any output"
        assert {c.doc_id for c in out.chunks} <= {doc_b}


@pytest.mark.asyncio
async def test_g5_5_walls_beat_grants_and_ownership_and_apply_on_the_next_request(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="drug_label")[2]
    _doc, _ = await ingest(
        env, item, admin_ctx(env), visibility="matter", matter=env.matter, tier=2
    )
    before = await retriever.retrieve(env.owner, "indications and usage")
    assert before.chunks, "the granted tenant reads the matter document"
    await world.wall(env.stack, env.ws, env.tenant, env.matter)  # created mid-session
    after = await retriever.retrieve(env.owner, "indications and usage")
    assert after.chunks == [], "the wall applies on the very next request"
    assert (await retriever.retrieve(admin_ctx(env), "indications and usage")).chunks, (
        "the wall is on the tenant only"
    )


@pytest.mark.asyncio
async def test_g5_5_a_walled_owner_cannot_read_their_own_document_in_that_matter(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="drug_label")[1]
    await ingest(env, item, env.owner, visibility="matter", matter=env.matter, tier=1)
    assert (await retriever.retrieve(env.owner, "warnings")).chunks
    await world.wall(env.stack, env.ws, env.tenant, env.matter)
    assert (await retriever.retrieve(env.owner, "warnings")).chunks == []


@pytest.mark.asyncio
async def test_g5_6_tier_ceilings_and_private_documents_are_enforced(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="drug_label")[2]
    await ingest(env, item, admin_ctx(env), visibility="matter", matter=env.matter, tier=4)
    assert (await retriever.retrieve(env.owner, "dosage")).chunks == [], (
        "the tenant's ceiling is 3; tier 4 is hidden"
    )
    assert (await retriever.retrieve(admin_ctx(env), "dosage")).chunks, (
        "admins read every tier of matter documents"
    )
    await ingest(env, load_corpus(kind="drug_label")[0], env.owner)  # a tenant's private document
    admin_out = await retriever.retrieve(admin_ctx(env), "Drug Facts active ingredients purpose")
    async with env.components.db.scoped(env.owner) as s:
        private_docs = {
            r[0]
            for r in (
                await s.execute(text("SELECT id FROM documents WHERE visibility = 'private'"))
            ).all()
        }
    assert not ({c.doc_id for c in admin_out.chunks} & private_docs), (
        "no break-glass session: private stays private"
    )


@pytest.mark.asyncio
async def test_g5_6_break_glass_needs_the_flag_and_an_active_session(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="drug_label")[1]
    doc_id, _ = await ingest(env, item, env.owner)
    admin = admin_ctx(env)
    assert (await retriever.retrieve(admin, "warnings")).chunks == []
    async with env.stack.identity.scoped(admin) as s:
        await s.execute(
            text("UPDATE workspaces SET admin_can_read_private = true WHERE id = :w"),
            {"w": env.ws.id},
        )
    assert (await retriever.retrieve(admin, "warnings")).chunks == [], (
        "the flag alone is not enough"
    )
    async with env.stack.identity.scoped(world.SYSTEM) as s:
        sid = (
            await s.execute(
                text(
                    "INSERT INTO access_sessions (org_id, workspace_id, user_id, kind, reason_code, expires_at)"
                    " VALUES (:o, :w, :u, 'break_glass', 'investigation', now() + interval '30 minutes') RETURNING id"
                ),
                {"o": env.org.id, "w": env.ws.id, "u": env.ws.admin},
            )
        ).scalar_one()
        for state in ("approved", "active"):
            await s.execute(
                text("UPDATE access_sessions SET state = :s WHERE id = :i"), {"s": state, "i": sid}
            )
    assert {c.doc_id for c in (await retriever.retrieve(admin, "warnings")).chunks} == {doc_id}, (
        "flag + session: allowed"
    )
    async with env.stack.identity.scoped(world.SYSTEM) as s:
        await s.execute(
            text("UPDATE access_sessions SET state = 'revoked' WHERE id = :i"), {"i": sid}
        )
    assert (await retriever.retrieve(admin, "warnings")).chunks == [], (
        "ending the session ends the access"
    )


@pytest.mark.asyncio
async def test_g5_8_a_stale_index_leaks_nothing_postgres_drops_the_id_and_counts_it(
    env: Env, retriever: Retriever
) -> None:
    item = load_corpus(kind="drug_label")[2]
    doc_id, _ = await ingest(
        env, item, admin_ctx(env), visibility="matter", matter=env.matter, tier=1
    )
    assert (await retriever.retrieve(env.owner, "indications")).chunks
    await env.pipeline.change_access(
        admin_ctx(env), doc_id, visibility="private", matter_id=None, tier=1
    )  # no re-index yet
    out = await retriever.retrieve(env.owner, "indications")
    assert out.chunks == [], "narrowed in Postgres: refused immediately"
    assert out.candidates > 0
    assert out.mismatches == out.candidates, (
        "Qdrant still listed them; Postgres dropped and counted"
    )
    assert retriever.mismatch_total >= out.mismatches
    assert all(d["reason"] == "postgres_refused" for d in out.dropped)
    await env.pipeline.apply_outbox(admin_ctx(env), doc_id)
    assert (await retriever.retrieve(env.owner, "indications")).candidates == 0, (
        "once re-indexed Qdrant stops returning them"
    )


@pytest.mark.asyncio
async def test_g5_12_qdrant_down_returns_unavailable_with_no_fallback_scan(
    env: Env, migrated_db: str, query_models
) -> None:
    await ingest(env, load_corpus(kind="drug_label")[1], env.owner)
    db = Database(role_dsn("svc_retrieval", migrated_db), pooled=False, use_null_pool=True)
    dead = Retriever(
        db,
        env.components.keys,
        VectorReader("http://127.0.0.1:1", "x", env.collection),
        query_models,
    )
    try:
        with pytest.raises(RetrievalUnavailableError):
            await dead.retrieve(env.owner, "warnings")
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_a_suspended_user_gets_nothing_at_once(env: Env, retriever: Retriever) -> None:
    await ingest(env, load_corpus(kind="drug_label")[1], env.owner)
    assert (await retriever.retrieve(env.owner, "warnings")).chunks
    async with env.stack.identity.scoped(world.SYSTEM) as s:
        await s.execute(
            text("UPDATE memberships SET state = 'suspended' WHERE user_id = :u"), {"u": env.tenant}
        )
    with pytest.raises(NoAccessError):
        await retriever.retrieve(env.owner, "warnings")


@pytest.mark.asyncio
async def test_g5_10_the_ledger_is_insert_only_for_retrieval_and_scoped_to_the_requesting_user(
    env: Env, retriever: Retriever, migrated_db: str
) -> None:
    await ingest(env, load_corpus(kind="drug_label")[1], env.owner)
    out = await retriever.retrieve(env.owner, "warnings")
    gen = Database(role_dsn("svc_generation", migrated_db), pooled=False, use_null_pool=True)
    try:
        async with gen.scoped(env.owner) as s:
            row = (
                await s.execute(
                    text("SELECT items FROM retrieval_records WHERE request_id = :r"),
                    {"r": out.request_id},
                )
            ).scalar_one()
        items = row if isinstance(row, list) else json.loads(row)
        kept = [i for i in items if i["alias"]]
        assert [i["alias"] for i in kept] == [f"chunk_{n}" for n in range(1, len(out.chunks) + 1)]
        assert {i["sha256"] for i in kept} == {c.text_sha256 for c in out.chunks}, (
            "hashes match chunk contents"
        )
        other = world.ctx(ContextRole.ADMIN, env.ws.org, env.ws.id, env.ws.admin)
        async with gen.scoped(other) as s:  # same workspace, different user: DEF-63
            assert (
                await s.execute(
                    text("SELECT count(*) FROM retrieval_records WHERE request_id = :r"),
                    {"r": out.request_id},
                )
            ).scalar_one() == 0
        with pytest.raises(Exception, match="permission denied"):
            async with gen.scoped(env.owner) as s:
                await s.execute(
                    text(
                        "INSERT INTO retrieval_records (org_id, workspace_id, request_id, user_id, scope_hash, items)"
                        " VALUES (:o, :w, :r, :u, 'x', '[]')"
                    ),
                    {"o": env.org.id, "w": env.ws.id, "r": uuid4(), "u": env.tenant},
                )
    finally:
        await gen.dispose()


@pytest.mark.asyncio
async def test_g5_11_ranking_is_deterministic_for_the_same_input(
    env: Env, retriever: Retriever
) -> None:
    await ingest(env, load_corpus(kind="contract")[2], env.owner)
    first = await retriever.retrieve(env.owner, "termination of the agreement")
    second = await retriever.retrieve(env.owner, "termination of the agreement")
    assert [c.chunk_id for c in first.chunks] == [c.chunk_id for c in second.chunks]
    assert [c.score for c in first.chunks] == [c.score for c in second.chunks]
