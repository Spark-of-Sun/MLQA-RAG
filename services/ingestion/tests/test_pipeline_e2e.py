"""Stage 4 end to end: real documents through every real service (G4.1, G4.7 to G4.11)."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING
from uuid import UUID

import pypdfium2 as pdfium
import pytest
from sqlalchemy import text

from ingestion.pipeline import DocumentHeldError
from lmqa_keys import Aad, DecryptionError, DocumentKeyDestroyedError, KeyService, decrypt
from lmqa_objectstore import ObjectNotFoundError, object_key
from lmqa_testing.corpus import load_corpus
from lmqa_vectorstore import SparseVec, VectorScope

if TYPE_CHECKING:
    from ingestion.pipeline import IngestResult
    from lmqa_db import DbContext

    from .conftest import Env

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_kms,
    pytest.mark.live_models,
    pytest.mark.stage4,
]
QUERY_SPARSE = SparseVec([1], [1.0])


async def ingest(
    env: Env,
    data: bytes,
    fmt: str,
    *,
    ctx: DbContext | None = None,
    title: str = "doc",
    visibility: str = "private",
    matter: UUID | None = None,
    tier: int = 1,
    claimed_sha: str | None = None,
) -> tuple[UUID, IngestResult]:
    ctx = ctx or env.owner
    upload = await env.pipeline.create_upload(ctx, title, visibility, matter, tier)
    await env.components.objects.put_quarantine(ctx.org_id, ctx.workspace_id, upload.doc_id, data)  # type: ignore[arg-type]
    result = await env.pipeline.complete_upload(
        ctx, upload.doc_id, fmt, claimed_sha or hashlib.sha256(data).hexdigest()
    )
    return upload.doc_id, result


async def chunk_texts(env: Env, ctx: DbContext, doc_id: UUID) -> dict[int, str]:
    async with env.components.db.scoped(ctx) as s:
        keys = await env.pipeline._keys(s, ctx)
        doc_key = await env.pipeline._doc_key(s, ctx, doc_id, keys.workspace_key)
        rows = (
            await s.execute(
                text("SELECT ordinal, text_ciphertext, text_sha256 FROM chunks WHERE doc_id = :d"),
                {"d": doc_id},
            )
        ).all()
    out = {}
    for ordinal, blob, digest in rows:
        plain = decrypt(
            doc_key, bytes(blob), Aad(ctx.org_id, ctx.workspace_id, doc_id, 1, ordinal)
        ).decode()  # type: ignore[arg-type]
        assert hashlib.sha256(plain.encode()).hexdigest() == digest, (
            "stored hash matches the decrypted text"
        )
        out[ordinal] = plain
    return out


async def vector_ids(env: Env, ctx: DbContext) -> set[UUID]:
    """Every point stored for the workspace (a scroll, so search candidate caps do not undercount)."""
    return set(await env.components.vectors.list_points(ctx.org_id, ctx.workspace_id))  # type: ignore[arg-type]


async def status(env: Env, ctx: DbContext, doc_id: UUID) -> str:
    async with env.components.db.scoped(ctx) as s:
        return str(
            (
                await s.execute(text("SELECT status FROM documents WHERE id = :d"), {"d": doc_id})
            ).scalar_one()
        )


@pytest.mark.parametrize(
    "kind", ["court_opinion", "contract", "regulation", "case_report", "drug_label"]
)
@pytest.mark.asyncio
async def test_a_real_document_becomes_encrypted_chunks_and_matching_vectors(
    env: Env, kind: str
) -> None:
    item = load_corpus(kind=kind)[0]
    doc_id, result = await ingest(env, item.data, item.format, title=item.title)
    assert (result.status, result.reason) == ("indexed", None)
    assert result.chunks >= 3
    texts = await chunk_texts(env, env.owner, doc_id)
    assert len(texts) == result.chunks
    assert all(t.strip() for t in texts.values())
    assert len(await vector_ids(env, env.owner)) == result.chunks, (
        "one vector per chunk, none for anything else"
    )
    async with env.components.db.scoped(env.owner) as s:
        row = (
            await s.execute(
                text(
                    "SELECT status, (SELECT index_state FROM document_versions WHERE doc_id = :d)"
                    " FROM documents WHERE id = :d"
                ),
                {"d": doc_id},
            )
        ).one()
        stored = (
            await s.execute(
                text("SELECT text_ciphertext FROM chunks WHERE doc_id = :d LIMIT 1"), {"d": doc_id}
            )
        ).scalar_one()
    assert tuple(row) == ("indexed", "in_sync")
    assert next(iter(texts.values()))[:30].encode() not in bytes(stored), (
        "chunk text is stored as ciphertext"
    )
    # The original is stored encrypted and the plaintext upload is gone from quarantine.
    async with env.components.db.scoped(env.owner) as s:
        keys = await env.pipeline._keys(s, env.owner)
        doc_key = await env.pipeline._doc_key(s, env.owner, doc_id, keys.workspace_key)
    original = await env.components.objects.get_decrypted(doc_key, env.org.id, env.ws.id, doc_id, 1)
    assert original == item.data
    with pytest.raises(ObjectNotFoundError):
        await env.components.objects.read_quarantine(env.org.id, env.ws.id, doc_id)


@pytest.mark.asyncio
async def test_g4_1_upload_safety_rejections_never_reach_the_parser_or_the_index(env: Env) -> None:
    pdf = load_corpus(kind="court_opinion")[0].data
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    active_pdf = (
        pdf[:2000]
        + b"\n1 0 obj << /Type /Action /S /JavaScript /JS (app.alert(1)) >> endobj\n"
        + pdf[2000:]
    )
    cases = [
        ("bad checksum", pdf, "pdf", "00" * 32, "checksum_mismatch"),
        ("EICAR control", eicar, "txt", None, "malware_eicar"),
        ("PDF active content", active_pdf, "pdf", None, "pdf_active_content"),
        ("type mismatch", pdf, "docx", None, "unsupported_format"),
        ("binary garbage", b"\x00\x01\x02" * 500, "txt", None, "unsupported_format"),
    ]
    for label, data, fmt, sha, reason in cases:
        doc_id, result = await ingest(env, data, fmt, claimed_sha=sha)
        assert (result.status, result.reason) == ("failed", reason), label
        assert await chunk_texts(env, env.owner, doc_id) == {}, f"{label}: nothing was chunked"
        with pytest.raises(ObjectNotFoundError):
            await env.components.objects.read_quarantine(env.org.id, env.ws.id, doc_id)
    assert await vector_ids(env, env.owner) == set(), (
        "nothing from a rejected upload was ever embedded"
    )


@pytest.mark.asyncio
async def test_a_page_without_a_text_layer_goes_to_ocr_review_and_is_never_embedded(
    env: Env,
) -> None:
    source = pdfium.PdfDocument(load_corpus(kind="court_opinion")[0].data)
    image = source[5].render(scale=1.3).to_pil().convert("L")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    doc_id, result = await ingest(env, buffer.getvalue(), "pdf")
    assert result.status == "ocr_review"
    assert result.ocr_pages == (1,)
    assert await status(env, env.owner, doc_id) == "ocr_review"
    assert await vector_ids(env, env.owner) == set()


@pytest.mark.asyncio
async def test_g4_9_the_same_file_in_two_workspaces_shares_nothing(env: Env) -> None:
    item = load_corpus(kind="drug_label")[0]
    doc_a, a = await ingest(env, item.data, item.format)
    ws2, ctx2 = await env.second_workspace()
    doc_b, b = await ingest(env, item.data, item.format, ctx=ctx2)
    assert a.chunks == b.chunks
    assert a.status == b.status == "indexed"
    assert object_key(env.org.id, env.ws.id, doc_a, 1) != object_key(env.org.id, ws2.id, doc_b, 1)
    async with env.components.db.scoped(env.owner) as s:
        rows_a = (
            await s.execute(
                text("SELECT id, text_ciphertext FROM chunks WHERE doc_id = :d ORDER BY ordinal"),
                {"d": doc_a},
            )
        ).all()
        wrapped_a = (
            await s.execute(
                text("SELECT wrapped_key FROM doc_keys WHERE doc_id = :d"), {"d": doc_a}
            )
        ).scalar_one()
    async with env.components.db.scoped(ctx2) as s:
        rows_b = (
            await s.execute(
                text("SELECT id, text_ciphertext FROM chunks WHERE doc_id = :d ORDER BY ordinal"),
                {"d": doc_b},
            )
        ).all()
        wrapped_b = (
            await s.execute(
                text("SELECT wrapped_key FROM doc_keys WHERE doc_id = :d"), {"d": doc_b}
            )
        ).scalar_one()
    assert {r[0] for r in rows_a}.isdisjoint({r[0] for r in rows_b}), (
        "distinct chunk IDs (and so vector IDs)"
    )
    assert all(bytes(x[1]) != bytes(y[1]) for x, y in zip(rows_a, rows_b, strict=True)), (
        "different ciphertext"
    )
    assert bytes(wrapped_a) != bytes(wrapped_b), "distinct document keys"
    assert (await chunk_texts(env, env.owner, doc_a)) == (await chunk_texts(env, ctx2, doc_b)), (
        "same plaintext, nothing shared"
    )
    assert not (await vector_ids(env, env.owner) & await vector_ids(env, ctx2))


@pytest.mark.asyncio
async def test_g4_10_an_access_change_reaches_the_vector_index_through_the_outbox(env: Env) -> None:
    item = load_corpus(kind="contract")[1]
    doc_id, result = await ingest(
        env, item.data, item.format, visibility="matter", matter=env.matter, tier=2
    )
    assert result.status == "indexed"
    owner_scope = VectorScope(env.org.id, env.ws.id, env.tenant, "tenant")
    stranger = VectorScope(env.org.id, env.ws.id, UUID(int=1), "tenant", grants={env.matter: 3})
    dense, sparse = await env.components.embedder.embed_query("agreement")
    assert len((await env.reader.search(stranger, dense, sparse, 500))[0]) == result.chunks, (
        "matter-shared: visible"
    )
    await env.pipeline.change_access(
        env.owner, doc_id, visibility="private", matter_id=None, tier=1
    )
    async with env.components.db.scoped(env.owner) as s:
        state = (
            await s.execute(
                text("SELECT index_state FROM document_versions WHERE doc_id = :d"), {"d": doc_id}
            )
        ).scalar_one()
        pending = (
            await s.execute(text("SELECT count(*) FROM index_outbox WHERE state = 'pending'"))
        ).scalar_one()
    assert (state, pending) == ("stale", 1), "Postgres changed first and the index is marked stale"
    assert await env.pipeline.apply_outbox(env.owner, doc_id) == 1
    assert (await env.reader.search(stranger, dense, sparse, 500))[0] == [], (
        "now private: gone from others' results"
    )
    assert len((await env.reader.search(owner_scope, dense, sparse, 500))[0]) == result.chunks, (
        "the owner still reads it"
    )
    assert await env.pipeline.apply_outbox(env.owner, doc_id) == 0, "idempotent"


@pytest.mark.asyncio
async def test_g4_11_deleting_a_document_destroys_its_key_and_removes_everything(env: Env) -> None:
    item = load_corpus(kind="case_report")[0]
    doc_id, result = await ingest(env, item.data, item.format)
    keeper, kept = await ingest(env, load_corpus(kind="drug_label")[0].data, "spl")
    assert result.status == kept.status == "indexed"
    async with env.components.db.scoped(env.owner) as s:
        keys = await env.pipeline._keys(s, env.owner)
        ciphertext = bytes(
            (
                await s.execute(
                    text("SELECT text_ciphertext FROM chunks WHERE doc_id = :d LIMIT 1"),
                    {"d": doc_id},
                )
            ).scalar_one()
        )
        wrapped_before = bytes(
            (
                await s.execute(
                    text("SELECT wrapped_key FROM doc_keys WHERE doc_id = :d"), {"d": doc_id}
                )
            ).scalar_one()
        )
    await env.pipeline.delete_document(env.owner, doc_id)
    async with env.components.db.scoped(env.owner) as s:
        key_row = (
            await s.execute(
                text("SELECT wrapped_key, state FROM doc_keys WHERE doc_id = :d"), {"d": doc_id}
            )
        ).one()
        chunk_count = (
            await s.execute(text("SELECT count(*) FROM chunks WHERE doc_id = :d"), {"d": doc_id})
        ).scalar_one()
        tomb = (
            await s.execute(
                text("SELECT count(*) FROM deletion_tombstones WHERE target_id = :d"), {"d": doc_id}
            )
        ).scalar_one()
    assert (key_row[0], key_row[1], chunk_count, tomb) == (None, "destroyed", 0, 1)
    assert await status(env, env.owner, doc_id) == "deleted"
    with pytest.raises(DocumentKeyDestroyedError):
        KeyService.open_document_key(keys.workspace_key, None, env.org.id, env.ws.id, doc_id)
    with pytest.raises(
        DecryptionError
    ):  # even a rescued ciphertext cannot be opened with any other key
        decrypt(keys.workspace_key, ciphertext, Aad(env.org.id, env.ws.id, doc_id, 1, 0))
    assert wrapped_before, (
        "a backup of the old wrapped key would still unwrap: the tombstone ledger covers that (doc 12.9)"
    )
    assert not await env.components.objects.exists(object_key(env.org.id, env.ws.id, doc_id, 1))
    remaining = await vector_ids(env, env.owner)
    assert len(remaining) == kept.chunks, "only the other document's vectors remain"
    assert len(await chunk_texts(env, env.owner, keeper)) == kept.chunks, (
        "the other document is untouched"
    )


@pytest.mark.asyncio
async def test_a_legal_hold_blocks_deletion_and_leaves_the_key_intact(
    env: Env, migrated_db: str
) -> None:
    import psycopg  # noqa: PLC0415

    from lmqa_db.bootstrap import with_database  # noqa: PLC0415
    from lmqa_testing.pg import superuser_dsn  # noqa: PLC0415

    doc_id, result = await ingest(env, load_corpus(kind="drug_label")[1].data, "spl")
    assert result.status == "indexed"
    with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as conn:
        conn.execute("UPDATE documents SET legal_hold = true WHERE id = %s", (doc_id,))
    with pytest.raises(DocumentHeldError):
        await env.pipeline.delete_document(env.owner, doc_id)
    async with env.components.db.scoped(env.owner) as s:
        wrapped = (
            await s.execute(
                text("SELECT wrapped_key FROM doc_keys WHERE doc_id = :d"), {"d": doc_id}
            )
        ).scalar_one()
    assert wrapped is not None, "the held document's key was not destroyed"
    assert await status(env, env.owner, doc_id) == "indexed"
    assert len(await chunk_texts(env, env.owner, doc_id)) == result.chunks
