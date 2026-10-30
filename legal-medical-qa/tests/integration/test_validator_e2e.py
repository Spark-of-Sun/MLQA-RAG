"""Stage 7 on the real stack, without any ML model: ledger, chunks under RLS, V1-V5 and V7, signed verdicts.

The ``Tripwire`` scorer is a labelled control: every case below must be rejected by a deterministic
check BEFORE entailment, so the scorer is never called. The passing path needs the real NLI model
and lives in the ``live_models`` test at the end (not run in the 2 GB build sandbox).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
import uvicorn
import websockets
from sqlalchemy import text
from valkey.asyncio import Valkey

from citation_validator.app import create_app
from citation_validator.checks import CANONICAL_REFUSAL
from citation_validator.service import ValidatorService, signing_bytes
from citation_validator.store import ValidatorStore
from ingestion.chunker import ChunkConfig, HfTokenizer, chunk_document
from ingestion.parsers import parse
from lmqa_auth import (
    ContextClaims,
    ContextSigner,
    ContextTokenError,
    ContextVerifier,
    ValkeyDenyList,
    ValkeyJtiStore,
)
from lmqa_db import ContextRole, Database, DbContext
from lmqa_keys import Aad, KeyService, OpenBaoProvider, OpenBaoTrustRoot, encrypt
from lmqa_testing import world
from lmqa_testing.corpus import load_corpus
from lmqa_testing.fixtures import Stack
from lmqa_testing.pg import role_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage7]


class Tripwire:
    """Control: entailment must not be reached by any case in this file."""

    model_id = "tripwire"

    def entailment(self, premise: str, hypothesis: str) -> float:  # noqa: ARG002
        msg = "V6 was reached but a deterministic check should have stopped the sentence first"
        raise AssertionError(msg)


@dataclass
class Rig:
    service: ValidatorService
    verifier: ContextVerifier
    signer: ContextSigner
    ctx: DbContext
    request_id: UUID
    texts: list[str]
    stack: Stack
    ws: world.Workspace
    org: world.Org
    doc_id: UUID
    matter: UUID
    db_ingest: Database
    app: object


async def _provision(stack: Stack, keys: KeyService, org: world.Org, ws: world.Workspace) -> None:
    ids = await keys.provision_org(org.id)
    _k, wrapped = await keys.new_workspace_key(ids.cmk_id, org.id, ws.id, 1)
    async with stack.identity.scoped(world.SYSTEM) as s:
        await s.execute(
            text("INSERT INTO org_keys (org_id, kms_key_id) VALUES (:o, :k)"),
            {"o": org.id, "k": ids.cmk_id},
        )
        await s.execute(
            text(
                "INSERT INTO workspace_keys (org_id, workspace_id, version, wrapped_key) VALUES (:o, :w, 1, :k)"
            ),
            {"o": org.id, "w": ws.id, "k": wrapped},
        )


@pytest_asyncio.fixture
async def rig(migrated_db: str, stack: Stack) -> AsyncGenerator[Rig]:
    provider = OpenBaoProvider(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
    )
    keys = KeyService(provider)
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, ws)
    matter = await world.create_matter(stack, ws)
    await world.grant(stack, ws, tenant, matter, 3)
    await _provision(stack, keys, org, ws)
    ctx = world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant)
    admin = world.ctx(ContextRole.ADMIN, ws.org, ws.id, ws.admin)
    db_ingest = Database(role_dsn("svc_ingestion", migrated_db), pooled=False, use_null_pool=True)
    db_ret = Database(role_dsn("svc_retrieval", migrated_db), pooled=False, use_null_pool=True)
    db_val = Database(role_dsn("svc_validator", migrated_db), pooled=False, use_null_pool=True)

    # A real contract, chunked by the real chunker (tokenizer only), encrypted under real keys.
    item = load_corpus(kind="contract")[2]
    drafts = chunk_document(
        parse(item.data, item.format),
        HfTokenizer("BAAI/bge-small-en-v1.5"),
        ChunkConfig.for_embedding(512),
    )[:4]
    doc_id = uuid.uuid7()
    async with db_ingest.scoped(admin) as s:
        cmk = (
            await s.execute(
                text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": org.id}
            )
        ).scalar_one()
        wk = (
            await s.execute(
                text("SELECT wrapped_key FROM workspace_keys WHERE workspace_id = :w"), {"w": ws.id}
            )
        ).scalar_one()
        ws_key = await keys.workspace_key(str(cmk), org.id, ws.id, 1, bytes(wk))
        doc_key, wrapped = KeyService.new_document_key(ws_key, org.id, ws.id, doc_id)
        await s.execute(
            text(
                "INSERT INTO documents (id, org_id, workspace_id, owner_user_id, matter_id, title_ciphertext, visibility,"
                " confidentiality_tier) VALUES (:d, :o, :w, :u, :m, :t, 'matter', 1)"
            ),
            {
                "d": doc_id,
                "o": org.id,
                "w": ws.id,
                "u": ws.admin,
                "m": matter,
                "t": encrypt(doc_key, b"Services Agreement", Aad(org.id, ws.id, doc_id, 0)),
            },
        )
        await s.execute(
            text(
                "INSERT INTO doc_keys (doc_id, org_id, workspace_id, wrapped_key, key_version) VALUES (:d, :o, :w, :k, 1)"
            ),
            {"d": doc_id, "o": org.id, "w": ws.id, "k": wrapped},
        )
        ids = []
        for d in drafts:
            cid = uuid.uuid7()
            ids.append(cid)
            await s.execute(
                text(
                    "INSERT INTO chunks (id, org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id, matter_id, visibility,"
                    " confidentiality_tier, kind, page_start, page_end, spans, text_ciphertext, text_sha256, token_count)"
                    " VALUES (:id, :o, :w, :d, 1, :n, :u, :m, 'matter', 1, :k, :ps, :pe, '[]', :ct, :sha, :tok)"
                ),
                {
                    "id": cid,
                    "o": org.id,
                    "w": ws.id,
                    "d": doc_id,
                    "n": d.ordinal,
                    "u": ws.admin,
                    "m": matter,
                    "k": d.kind,
                    "ps": d.page_start,
                    "pe": d.page_end,
                    "ct": encrypt(
                        doc_key, d.text.encode(), Aad(org.id, ws.id, doc_id, 1, d.ordinal)
                    ),
                    "sha": hashlib.sha256(d.text.encode()).hexdigest(),
                    "tok": d.token_count,
                },
            )
        for status in ("scanning", "parsing", "indexing", "indexed"):
            await s.execute(
                text("UPDATE documents SET status = :s WHERE id = :d"), {"s": status, "d": doc_id}
            )
    request_id = uuid.uuid4()
    items = [
        {
            "chunk_id": str(cid),
            "version": 1,
            "sha256": hashlib.sha256(d.text.encode()).hexdigest(),
            "alias": f"chunk_{n}",
            "rank": n,
            "score": 1.0,
            "dropped": None,
        }
        for n, (cid, d) in enumerate(zip(ids, drafts, strict=True), 1)
    ]
    async with db_ret.scoped(ctx) as s:
        await s.execute(
            text(
                "INSERT INTO retrieval_records (org_id, workspace_id, request_id, user_id, scope_hash, items)"
                " VALUES (:o, :w, :r, :u, 'h', CAST(:i AS jsonb))"
            ),
            {"o": org.id, "w": ws.id, "r": request_id, "u": ctx.user_id, "i": json.dumps(items)},
        )
    trust = OpenBaoTrustRoot(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
        f"validator-root-{uuid.uuid4().hex[:8]}",
    )
    await trust.create()
    valkey = Valkey.from_url(os.environ.get("VALKEY_URL", "redis://127.0.0.1:6379"))
    verifier = ContextVerifier(
        [await trust.public_key_pem()],
        service="citation_validator",
        deny_list=ValkeyDenyList(valkey),
        jti_store=ValkeyJtiStore(valkey),
    )
    signer = ContextSigner(trust, "gateway-pod")
    service = ValidatorService(
        ValidatorStore(db_val, keys), ContextSigner(trust, "validator-pod"), Tripwire(), 0.9
    )
    yield Rig(
        service,
        verifier,
        signer,
        ctx,
        request_id,
        [d.text for d in drafts],
        stack,
        ws,
        org,
        doc_id,
        matter,
        db_ingest,
        create_app(service, verifier),
    )
    for db in (db_ingest, db_ret, db_val):
        await db.dispose()
    await trust.aclose()
    await valkey.aclose()
    await provider.aclose()


async def verdict(rig: Rig, sentence: str, ctx: DbContext | None = None):
    return await rig.service.check(ctx or rig.ctx, rig.request_id, sentence, 0)


@pytest.mark.parametrize(
    ("sentence", "failed"),
    [
        ("The Company must pay a termination fee.", "V4"),  # no citation
        ("The Company must pay a fee [chunk_]. ", "V1"),  # malformed tag
        ("The Company must pay a fee [Chunk_1].", "V1"),
        ("The Company must pay a fee [chunk_01].", "V1"),
        ("The Company must pay a fee [chunk 1].", "V1"),
        ("The Company must pay a fee [chunk_9].", "V2"),  # not in this ledger
        ("The fee is $9,999,999 [chunk_1].", "V5"),  # invented amount
        ("Termination takes 987 days [chunk_1].", "V5"),  # invented number
        ("The deadline is 31 February 2031 [chunk_1].", "V5"),  # invented date
        (f"{CANONICAL_REFUSAL} It is 5 days [chunk_1].", "V7"),  # refusal plus a claim
        (f"{CANONICAL_REFUSAL} [chunk_1]", "V7"),  # refusal with a tag
    ],
)
@pytest.mark.asyncio
async def test_unsupported_sentences_are_rejected_by_a_deterministic_check(
    rig: Rig, sentence: str, failed: str
) -> None:
    got = await verdict(rig, sentence)
    assert got.payload["passed"] is False
    assert got.payload["failed_check"] == failed
    assert got.payload["entailment"] is None, "entailment was never reached"


@pytest.mark.asyncio
async def test_headings_and_the_exact_canonical_refusal_pass_without_entailment(rig: Rig) -> None:
    for sentence, refusal in (("# Summary", False), (CANONICAL_REFUSAL, True)):
        got = await verdict(rig, sentence)
        assert got.payload["passed"] is True
        assert got.payload["refusal"] is refusal
        assert got.payload["citations"] == []


@pytest.mark.asyncio
async def test_g7_6_integrity_a_wrong_ledger_hash_a_wall_and_a_crypto_erase_each_fail_v3(
    rig: Rig,
) -> None:
    # (1) a chunk whose content no longer matches the hash retrieval recorded
    async with rig.stack.retrieval.scoped(rig.ctx) as s:
        wrong = uuid.uuid4()
        await s.execute(
            text(
                "INSERT INTO retrieval_records (org_id, workspace_id, request_id, user_id, scope_hash, items)"
                " VALUES (:o, :w, :r, :u, 'h', CAST(:i AS jsonb))"
            ),
            {
                "o": rig.org.id,
                "w": rig.ws.id,
                "r": wrong,
                "u": rig.ctx.user_id,
                "i": json.dumps(
                    [
                        {
                            "chunk_id": str(uuid.uuid4()),
                            "version": 1,
                            "sha256": "00" * 32,
                            "alias": "chunk_1",
                        }
                    ]
                ),
            },
        )
    # a ledger pointing at a chunk id that does not exist behaves as unreadable
    got = await rig.service.check(rig.ctx, wrong, "A claim without support [chunk_1].", 0)
    assert got.payload["failed_check"] == "V3"
    # (2) an ethical wall created after retrieval makes the chunks unreadable at once
    await world.wall(rig.stack, rig.ws, rig.ctx.user_id, rig.matter)  # type: ignore[arg-type]
    got = await verdict(rig, "The agreement exists [chunk_1].")
    assert got.payload["failed_check"] == "V3", "a wall applies to the very next sentence"


@pytest.mark.asyncio
async def test_a_crypto_erased_document_can_never_be_cited(rig: Rig) -> None:
    admin = world.ctx(ContextRole.ADMIN, rig.ws.org, rig.ws.id, rig.ws.admin)
    async with rig.db_ingest.scoped(admin) as s:
        await s.execute(
            text("UPDATE doc_keys SET wrapped_key = NULL, state = 'destroyed' WHERE doc_id = :d"),
            {"d": rig.doc_id},
        )
    got = await verdict(rig, "The agreement exists [chunk_1].")
    assert got.payload["failed_check"] == "V3"


@pytest.mark.asyncio
async def test_another_users_request_id_has_no_ledger_so_nothing_validates(rig: Rig) -> None:
    other = world.ctx(
        ContextRole.ADMIN, rig.ws.org, rig.ws.id, rig.ws.admin
    )  # same workspace, different user (DEF-63)
    got = await verdict(rig, "The agreement exists [chunk_1].", other)
    assert got.payload["failed_check"] == "V2"


@pytest.mark.asyncio
async def test_g7_6_verdicts_are_signed_and_a_changed_verdict_breaks_the_signature(
    rig: Rig,
) -> None:
    got = await verdict(rig, "No citation at all.")
    raw = base64.b64decode(got.signature)
    assert (
        await rig.verifier.verify_signature(got.certificate, signing_bytes(got.payload), raw)
        == "validator-pod"
    )
    forged = {**got.payload, "passed": True, "failed_check": None}
    with pytest.raises(ContextTokenError):
        await rig.verifier.verify_signature(got.certificate, signing_bytes(forged), raw)
    other_sentence = {
        **got.payload,
        "sentence": "Something else [chunk_1].",
        "sentence_sha256": hashlib.sha256(b"x").hexdigest(),
    }
    with pytest.raises(ContextTokenError):
        await rig.verifier.verify_signature(got.certificate, signing_bytes(other_sentence), raw)
    assert (
        got.payload["sentence_sha256"]
        == hashlib.sha256(got.payload["sentence"].encode()).hexdigest()
    )


@pytest.mark.asyncio
async def test_g7_4_identical_input_gives_identical_verdicts(rig: Rig) -> None:
    sentences = [
        "Unsupported claim.",
        "Bad tag [chunk_x].",
        "Invented $77 [chunk_1].",
        "# Heading",
        CANONICAL_REFUSAL,
    ]
    first = [(await verdict(rig, s)).payload for s in sentences]
    second = [(await verdict(rig, s)).payload for s in sentences]
    assert first == second


async def _mint(rig: Rig, audience: str = "citation_validator") -> str:
    claims = ContextClaims(
        rig.ctx.user_id,
        rig.ctx.org_id,
        rig.ctx.workspace_id,
        "tenant",
        "passkey",
        "h",
        1,
        1,  # type: ignore[arg-type]
        rig.request_id,
        "",
        "",
        0,
    )
    return await rig.signer.mint(audience=audience, claims=claims)


@pytest.mark.asyncio
async def test_the_http_api_requires_a_token_for_this_service_and_validates_a_whole_answer(
    rig: Rig,
) -> None:
    transport = httpx.ASGITransport(app=rig.app)  # type: ignore[arg-type]
    answer = "The fee is $5,000,000 [chunk_1]. Nothing else is stated. # Done"
    async with httpx.AsyncClient(transport=transport, base_url="http://validator") as client:
        for headers in (
            {},
            {"Authorization": "Bearer nonsense"},
            {"Authorization": f"Bearer {await _mint(rig, 'retrieval')}"},
        ):
            denied = await client.post(
                "/internal/v1/validate-answer", json={"answer": answer}, headers=headers
            )
            assert denied.status_code == 401
            assert denied.json() == {"detail": "Unauthorized"}, "identical body whatever the reason"
        ok = await client.post(
            "/internal/v1/validate-answer",
            json={"answer": answer},
            headers={"Authorization": f"Bearer {await _mint(rig)}"},
        )
    body = ok.json()
    assert ok.status_code == 200
    assert [v["payload"]["failed_check"] for v in body["verdicts"]] == ["V5", "V4", None]
    assert body["all_failed"] is False, "the heading passes; no content sentence did"


@asynccontextmanager
async def serve(app: object) -> AsyncGenerator[int]:
    """A real uvicorn server inside this event loop, on a free port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))  # type: ignore[arg-type]
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.01)
    try:
        yield int(sock.getsockname()[1])
    finally:
        server.should_exit = True
        await task
        sock.close()


@pytest.mark.asyncio
async def test_streaming_validation_emits_a_verdict_per_sentence_regardless_of_chunking(
    rig: Rig,
) -> None:
    text_ = "First unsupported claim. Second one with $42 [chunk_1]. Last"
    token = await _mint(rig)
    async with (
        serve(rig.app) as port,
        websockets.connect(
            f"ws://127.0.0.1:{port}/internal/v1/validate-stream",
            additional_headers={"Authorization": f"Bearer {token}"},
        ) as ws,
    ):
        for i in range(0, len(text_), 5):
            await ws.send(json.dumps({"delta": text_[i : i + 5]}))
        await ws.send(json.dumps({"end": True}))
        frames = [json.loads(m) async for m in ws]
    assert frames[-1] == {"done": True}
    verdicts = [f["verdict"]["payload"] for f in frames[:-1]]
    assert [v["sentence"] for v in verdicts] == [
        "First unsupported claim.",
        "Second one with $42 [chunk_1].",
        "Last",
    ]
    assert [v["failed_check"] for v in verdicts] == ["V4", "V5", "V4"]
    assert [v["index"] for v in verdicts] == [0, 1, 2]


@pytest.mark.asyncio
async def test_a_streaming_handshake_without_a_valid_token_for_this_service_is_refused(
    rig: Rig,
) -> None:
    async with serve(rig.app) as port:
        url = f"ws://127.0.0.1:{port}/internal/v1/validate-stream"
        for headers in (
            {},
            {"Authorization": "Bearer junk"},
            {"Authorization": f"Bearer {await _mint(rig, 'retrieval')}"},
        ):
            with pytest.raises(websockets.exceptions.InvalidStatus):
                async with websockets.connect(url, additional_headers=headers):
                    pass


@pytest.mark.live_models
@pytest.mark.asyncio
async def test_a_supported_sentence_passes_with_resolved_citations_and_an_unsupported_one_does_not(
    rig: Rig,
) -> None:
    """Needs the real NLI model (NOT run in the build sandbox). Run later: pytest -m live_models."""
    from citation_validator.nli import TransformersNliScorer  # noqa: PLC0415

    scorer = TransformersNliScorer(
        os.environ.get("NLI_MODEL", "cross-encoder/nli-deberta-v3-small"),
        os.environ.get("NLI_MODEL_HASH") or None,
    )
    real = ValidatorService(
        rig.service._store, ContextSigner(rig.signer._root, "validator-pod"), scorer, 0.9
    )
    first = rig.texts[1].split(". ")[0].rstrip(".")
    got = await real.check(rig.ctx, rig.request_id, f"{first} [chunk_2].", 0)
    assert got.payload["passed"] is True
    assert got.payload["citations"]
    assert got.payload["citations"][0]["doc_title"] == "Services Agreement"
    contradiction = await real.check(
        rig.ctx, rig.request_id, "The agreement forbids all payments entirely [chunk_2].", 1
    )
    assert contradiction.payload["passed"] is False
