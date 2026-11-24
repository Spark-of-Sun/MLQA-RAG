"""Background ingestion worker: parse -> chunk -> embed -> store -> audit (blueprint 11.1 steps 4 to 10).

Each passage is embedded with its document title and section path in front (contextual chunk headers), so a
passage that only says "within 30 days" is still found by a question about the agreement and section it belongs
to. Embeddings already computed for the same text and model in the same organization are reused from
`embedding_cache` instead of being sent to the provider again.

A document becomes searchable only when all its chunks and vectors are written in one transaction, so a
failure never leaves a partial chunk set (step 8). Re-running a job replaces its chunks (idempotent, G4.7).
Jobs left `processing` by a restart are resumed at startup.

Chunk text and section are stored sealed with the document's key (text_ct, section_ct; lmqa_keys, R-51.3). The
full-text columns are computed from the plaintext in the insert and stored stripped of positions (0012).
"""

from __future__ import annotations

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psycopg

import lmqa_audit
from ingestion.chunker import build_chunks, sha256_text
from ingestion.parsers import ParseError, parse
from lmqa_db import Claims, Database
from lmqa_keys import Field, FieldCipher
from lmqa_models.contracts import feature_enabled
from lmqa_objectstore import ObjectStore
from lmqa_vectorstore import EmbeddingError, TextEmbedder, vector_literal

log = logging.getLogger(__name__)
EMBED_BATCH = 50  # passages per embedding request, and per cache write


def embedding_input(title: str, section: str | None, text: str) -> str:
    """The text that is embedded for a passage: its document and section path, then the passage itself."""
    return "\n".join(x for x in (title, section, text) if x)


def _access(conn: psycopg.Connection[Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Who may see the document. The title stays out of audit metadata (R-60.5). Named shares are a frozen
    MVP-only feature (DEV-21): `document_shares` is read only while `named_shares` is on."""
    rows = (
        conn.execute(
            "select user_id from document_shares where document_id = %s order by created_at",
            [doc["id"]],
        ).fetchall()
        if feature_enabled("named_shares")
        else []
    )
    return {
        "visibility": doc["visibility"],
        "shared_with": [str(r["user_id"]) for r in rows],
    }


CHUNK_INSERT = (
    "insert into chunks (id, org_id, workspace_id, document_id, owner_id, visibility, ordinal, kind,"
    " section_ct, page_start, page_end, text_ct, text_sha256, token_count, embedding, embedding_model, tsv,"
    " tsv_simple)"
    " values (%(id)s, %(org_id)s, %(workspace_id)s, %(document_id)s, %(owner_id)s, %(visibility)s, %(ordinal)s,"
    " %(kind)s, %(section_ct)s, %(page_start)s, %(page_end)s, %(text_ct)s, %(text_sha256)s, %(token_count)s,"
    " %(embedding)s::vector, %(embedding_model)s,"
    " strip(to_tsvector('english', coalesce(%(section)s, '') || ' ' || %(text)s)),"
    " strip(to_tsvector('simple', coalesce(%(section)s, '') || ' ' || %(text)s)))"
)


class Ingestor:
    def __init__(
        self,
        db: Database,
        store: ObjectStore,
        embedder: TextEmbedder,
        keys: FieldCipher,
        *,
        workers: int = 2,
    ) -> None:
        self._db = db
        self._store = store
        self._embedder = embedder
        self._keys = keys
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ingest")

    def submit(self, doc_id: str) -> None:
        self._pool.submit(self.run_safely, str(doc_id))

    def resume_pending(self) -> int:
        # Cross-workspace by nature: only the ids, through the narrow definer helper (17_ingestion.sql).
        with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            rows = conn.execute("select id from app_ingest_pending() as id").fetchall()
        for row in rows:
            self.submit(str(row["id"]))
        return len(rows)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def run_safely(self, doc_id: str) -> None:
        try:
            self.run(doc_id)
        except ParseError as exc:
            self._fail(doc_id, str(exc), reason="parse")
        except EmbeddingError as exc:
            self._fail(doc_id, f"Indexing failed: {exc}", reason="embedding")
        except Exception:
            log.exception("ingestion of %s failed", doc_id)
            self._fail(doc_id, "Unexpected error while processing the document.", reason="internal")

    def _uploader(self, doc_id: str) -> Claims | None:
        """The job acts as the uploader (the policies admit nothing else); None once the document left processing."""
        with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            row = conn.execute("select app_ingest_principal(%s) as owner", [doc_id]).fetchone()
        return Claims(user_id=row["owner"]) if row and row["owner"] else None

    def run(self, doc_id: str) -> None:
        claims = self._uploader(doc_id)
        if claims is None:
            return
        with self._db.as_service("ingestion", claims) as conn:
            doc = conn.execute("select * from documents where id = %s", [doc_id]).fetchone()
            if doc is None or doc["status"] != "processing":
                return
            doc["title"] = (
                self._keys.open(
                    conn,
                    Field.document("document.title", doc["org_id"], doc["workspace_id"], doc["id"]),
                    doc["title_ct"],
                )
                or ""
            )
        parsed = parse(doc["file_type"], self._store.get(doc["object_key"]))
        chunks, structure = build_chunks(parsed.blocks)
        if not chunks:
            raise ParseError("No text found in the file.")
        inputs = [embedding_input(doc["title"], c.section, c.text) for c in chunks]
        model, vectors, reused = self._embed_cached(claims, str(doc["org_id"]), inputs)
        notes = None
        if parsed.pages_without_text:
            listed = ", ".join(str(n) for n in parsed.pages_without_text[:20])
            more = "…" if len(parsed.pages_without_text) > 20 else ""
            notes = (
                f"{len(parsed.pages_without_text)} page(s) have no text layer and are not searchable "
                f"(OCR is a later stage): {listed}{more}"
            )
        with self._db.as_service("ingestion", claims) as conn:
            current = conn.execute(
                "select status from documents where id = %s for update", [doc_id]
            ).fetchone()
            if current is None or current["status"] != "processing":
                return  # deleted while we worked
            conn.execute("delete from chunks where document_id = %s", [doc_id])
            # Normally created at upload; idempotent, so a document from another path gets its key here.
            self._keys.new_document(conn, doc["org_id"], doc["workspace_id"], doc["id"])
            rows = []
            for c, v in zip(chunks, vectors, strict=True):
                chunk_id = str(uuid.uuid4())
                scope = (doc["org_id"], doc["workspace_id"], doc["id"], chunk_id, 1)
                rows.append(
                    {
                        "id": chunk_id,
                        "org_id": doc["org_id"],
                        "workspace_id": doc["workspace_id"],
                        "document_id": doc["id"],
                        "owner_id": doc["owner_id"],
                        "visibility": doc["visibility"],
                        "ordinal": c.ordinal,
                        "kind": c.kind,
                        "section": c.section,
                        "section_ct": self._keys.seal(
                            conn, Field.chunk("chunk.section", *scope), c.section
                        ),
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "text": c.text,
                        "text_ct": self._keys.seal(conn, Field.chunk("chunk.text", *scope), c.text),
                        "text_sha256": c.sha256,
                        "token_count": c.token_count,
                        "embedding": vector_literal(v),
                        "embedding_model": model,
                    }
                )
            with conn.cursor() as cur:
                cur.executemany(CHUNK_INSERT, rows)
            conn.execute(
                "update documents set status = 'ready', error = null, notes = %s, page_count = %s,"
                " chunk_count = %s, structure = %s, updated_at = now() where id = %s",
                [notes, parsed.page_count, len(chunks), structure, doc_id],
            )
            lmqa_audit.append(
                conn,
                org_id=doc["org_id"],
                workspace_id=doc["workspace_id"],
                actor_id=doc["owner_id"],
                action="document.indexed",
                target_type="document",
                target_id=doc_id,
                payload={
                    "chunks": len(chunks),
                    "structure": structure,
                    "pages": parsed.page_count,
                    "embedding_model": model,
                    **_access(conn, doc),
                },
            )
        log.info(
            "indexed document %s: %d chunks (%s) with %s, %d embeddings reused",
            doc_id,
            len(chunks),
            structure,
            model,
            reused,
        )

    def _embed_cached(
        self, claims: Claims, org_id: str, inputs: list[str]
    ) -> tuple[str, list[list[float]], int]:
        """(model, vectors, reused) for `inputs`, all from one embedding model.

        Models are tried in preference order. Vectors already in `embedding_cache` are reused; new ones are written
        to the cache batch by batch as they arrive, so quota spent on a document is never lost, even if the model's
        daily quota runs out halfway and the document moves to the next model."""
        hashes = [sha256_text(t) for t in inputs]
        texts = dict(zip(hashes, inputs, strict=True))
        models = self._embedder.available() or self._embedder.models
        last: EmbeddingError | None = None
        for model in models:
            with self._db.as_service("ingestion", claims) as conn:
                rows = conn.execute(
                    "select text_sha256, embedding::text as v from embedding_cache"
                    " where org_id = %s and model = %s and text_sha256 = any(%s)",
                    [org_id, model, list(texts)],
                ).fetchall()
            vectors = {r["text_sha256"]: [float(x) for x in json.loads(r["v"])] for r in rows}
            reused = len(vectors)
            todo = [h for h in texts if h not in vectors]
            try:
                for start in range(0, len(todo), EMBED_BATCH):
                    batch = todo[start : start + EMBED_BATCH]
                    fresh = self._embedder.embed_documents([texts[h] for h in batch], model)
                    with (
                        self._db.as_service("ingestion", claims) as conn,
                        conn.cursor() as cur,
                    ):
                        cur.executemany(
                            "insert into embedding_cache (org_id, model, text_sha256, embedding)"
                            " values (%s, %s, %s, %s::vector) on conflict do nothing",
                            [
                                (org_id, model, h, vector_literal(v))
                                for h, v in zip(batch, fresh, strict=True)
                            ],
                        )
                    vectors.update(zip(batch, fresh, strict=True))
            except EmbeddingError as exc:
                last = exc
                if len(models) > 1:
                    log.warning(
                        "embedding with %s failed (%s); trying the next embedding model", model, exc
                    )
                self._embedder.mark_down(model)
                continue
            return model, [vectors[h] for h in hashes], reused
        raise last or EmbeddingError("no embedding model is configured")

    def _fail(self, doc_id: str, message: str, *, reason: str) -> None:
        claims = self._uploader(doc_id)
        if claims is None:
            return
        with self._db.as_service("ingestion", claims) as conn:
            doc = conn.execute(
                "update documents set status = 'failed', error = %s, updated_at = now()"
                " where id = %s and status = 'processing'"
                " returning id, org_id, workspace_id, owner_id, visibility",
                [message[:500], doc_id],
            ).fetchone()
            if doc:
                lmqa_audit.append(
                    conn,
                    org_id=doc["org_id"],
                    workspace_id=doc["workspace_id"],
                    actor_id=doc["owner_id"],
                    action="document.failed",
                    target_type="document",
                    target_id=doc_id,
                    payload={"reason": reason, **_access(conn, doc)},
                )
