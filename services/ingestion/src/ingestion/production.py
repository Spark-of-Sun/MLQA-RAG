"""Production ingestion: queue, worker steps, indexer, reconciler and crypto-erase (blueprint 9.3, 10.5, 10.6, 11.1,
12, G4.1 to G4.12). Entry points (each its own process in production, D18):

    python -m ingestion.production worker      Procrastinate worker on a direct connection (LISTEN/NOTIFY)
    python -m ingestion.production indexer     applies index_outbox to Qdrant (payload updates and deletes)
    python -m ingestion.production reconciler  compares PostgreSQL and Qdrant per workspace and repairs drift

Jobs are deferred with Procrastinate's SQL function inside the same transaction as the document row (G0.13), so a
job never exists without its document. Fair share: each workspace has N lock slots `ws:{id}:slot:{k}` (N = its
concurrency cap), so one workspace's 500-page uploads cannot starve another's (G4.8). The job carries a signed
envelope (lmqa_auth.sign_envelope); the worker verifies it, then re-reads the document, owner and workspace from
PostgreSQL and aborts if any is gone or changed (`pv` mismatch, G4.7).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import procrastinate

import lmqa_audit
from ingestion.scan import ScanRefusedError, scan_bytes, strip_pdf_active_content
from lmqa_auth.context import ContextTokenError, Signer, sign_envelope, verify_envelope
from lmqa_db import Claims, Database, dsn
from lmqa_keys import FieldCipher, field_cipher_from_settings
from lmqa_keys.keyring import KeyRing
from lmqa_models.contracts import feature_enabled
from lmqa_models.infra import load_infra_settings
from lmqa_models.settings import Settings, load_settings
from lmqa_security.redact import configure_logging
from lmqa_vectorstore.qdrant import ChunkPoint, VectorWriter, point_id

log = logging.getLogger("ingestion.production")
QUEUE = "ingest"
DEFAULT_SLOTS = 2
ORPHAN_GRACE_SECONDS = 600

_DEFER_SQL = """
select procrastinate_defer_jobs_v2(array[
    row(%(queue)s, 'ingestion.ingest', 0, %(lock)s, null, %(args)s::jsonb, null, 'ordered')
        ::procrastinate_job_to_defer_v2
])
"""


def slot_lock(workspace_id: str, document_id: str, slots: int = DEFAULT_SLOTS) -> str:
    return f"ws:{workspace_id}:slot:{int(document_id.replace('-', ''), 16) % max(1, slots)}"


def defer_ingest(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
    conn: Any,
    signer: Signer,
    *,
    org_id: str,
    workspace_id: str,
    owner_id: str,
    document_id: str,
    version: int,
    visibility: str,
    pv: int,
    slots: int = DEFAULT_SLOTS,
) -> int:
    """Call inside the transaction that inserted the document row."""
    envelope = sign_envelope(
        signer,
        {
            "org_id": org_id,
            "workspace_id": workspace_id,
            "owner_user_id": owner_id,
            "doc_id": document_id,
            "doc_version": version,
            "visibility": visibility,
            "pv": pv,
        },
    )
    row = conn.execute(
        _DEFER_SQL,
        {
            "queue": QUEUE,
            "lock": slot_lock(workspace_id, document_id, slots),
            "args": json.dumps({"envelope": envelope}),
        },
    ).fetchone()
    return int((row["procrastinate_defer_jobs_v2"] if isinstance(row, dict) else row[0])[0])


@dataclass
class WorkerDeps:
    settings: Settings
    db: Database
    keyring: KeyRing
    trust_bundle: list[tuple[str, bytes]]
    run_mvp_pipeline: Callable[[str], None]  # parse, chunk, embed (ingestion.pipeline.Ingestor.run)
    vectors: VectorWriter | None
    object_store: Any | None  # lmqa_objectstore.s3.S3ObjectStore
    sparse: Callable[[list[str]], list[tuple[list[int], list[float]]]] | None = None


def build_app(settings: Settings) -> procrastinate.App:
    # Direct connection: LISTEN/NOTIFY and the worker's session state do not survive transaction pooling (4.8).
    return procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=dsn(settings, "svc_ingestion"))
    )


def register_tasks(app: procrastinate.App, deps: WorkerDeps) -> None:
    @app.task(
        name="ingestion.ingest",
        queue=QUEUE,
        retry=procrastinate.RetryStrategy(max_attempts=5, exponential_wait=5),
    )
    def ingest(envelope: dict[str, Any]) -> None:
        IngestJob(deps).run(envelope)


class IngestJob:
    def __init__(self, deps: WorkerDeps) -> None:
        self.d = deps

    def run(self, envelope: dict[str, Any]) -> None:
        try:
            body = verify_envelope(
                envelope, self.d.trust_bundle, identities=("gateway", "ingestion")
            )
        except ContextTokenError:
            log.warning("ingest job refused: envelope invalid or expired")
            return  # not retried: a tampered or expired envelope never becomes valid
        doc_id, ws, org, owner = (
            body["doc_id"],
            body["workspace_id"],
            body["org_id"],
            body["owner_user_id"],
        )
        if not self._still_valid(body):
            log.info("ingest job aborted: document, owner or workspace changed since enqueue")
            return
        if feature_enabled("malware_scan_ocr"):
            try:
                self._scan(org, ws, doc_id)
            except ScanRefusedError as exc:
                self._fail(doc_id, org, ws, exc.reason)
                return
        self.d.run_mvp_pipeline(
            doc_id
        )  # parse, chunk, embed; writes chunks under the document's owner
        if feature_enabled("qdrant_vectors") and self.d.vectors is not None:
            self._index_vectors(org, ws, doc_id)
        with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            conn.execute(
                "update documents set lifecycle = 'indexed' where id = %s and status = 'ready'",
                [doc_id],
            )
            lmqa_audit.append(
                conn,
                org_id=org,
                workspace_id=ws,
                actor_id=owner,
                action="document.indexed",
                target_type="document",
                target_id=doc_id,
                payload={"version": body["doc_version"]},
            )

    def _still_valid(self, body: dict[str, Any]) -> bool:
        with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            row = conn.execute(
                "select d.owner_id, d.workspace_id, w.status as ws_status, m.status as m_status,"
                " m.principal_version from documents d join workspaces w on w.id = d.workspace_id"
                " join memberships m on m.user_id = d.owner_id and m.workspace_id = d.workspace_id"
                " where d.id = %s",
                [body["doc_id"]],
            ).fetchone()
        return bool(
            row
            and str(row["owner_id"]) == body["owner_user_id"]
            and row["ws_status"] == "active"
            and row["m_status"] == "active"
            and int(row["principal_version"]) == int(body["pv"])
        )

    def _scan(self, org: str, ws: str, doc_id: str) -> None:
        infra = load_infra_settings()
        with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            doc = conn.execute(
                "select object_key, file_type from documents where id = %s", [doc_id]
            ).fetchone()
        from lmqa_objectstore import ObjectStore

        local = ObjectStore(self.d.settings.data_dir / "objects")
        data = local.get(doc["object_key"])
        scan_bytes(data, host=infra.clamav_host, port=infra.clamav_port)
        if doc["file_type"] == "pdf":
            cleaned, removed = strip_pdf_active_content(data)
            if removed:
                local.put(doc["object_key"], cleaned)
                with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
                    lmqa_audit.append(
                        conn,
                        org_id=org,
                        workspace_id=ws,
                        action="document.sanitized",
                        target_type="document",
                        target_id=doc_id,
                        payload={"removed": removed},
                    )

    def _index_vectors(self, org: str, ws: str, doc_id: str) -> None:
        with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            keys = FieldCipher(self.d.keyring)
            rows = [
                keys.open_chunk_row(conn, dict(r))
                for r in conn.execute(
                    "select id, org_id, workspace_id, document_id, version, owner_id, visibility, matter_id, tier,"
                    " embedding::text as emb, embedding_model, section_ct, text_ct from chunks"
                    " where document_id = %s and embedding is not null"
                    " and (ocr_confidence is null or ocr_confidence >= 0)",
                    [doc_id],
                ).fetchall()
            ]
        sparse = (
            self.d.sparse([f"{r['section'] or ''} {r['text']}" for r in rows])
            if self.d.sparse
            else []
        )
        points = []
        for i, r in enumerate(rows):
            idx, val = sparse[i] if sparse else ([], [])
            points.append(
                ChunkPoint(
                    chunk_id=str(r["id"]),
                    document_id=str(r["document_id"]),
                    version=int(r["version"]),
                    org_id=org,
                    workspace_id=ws,
                    owner_id=str(r["owner_id"]),
                    visibility=r["visibility"],
                    matter_id=str(r["matter_id"]) if r["matter_id"] else None,
                    tier=int(r["tier"]),
                    dense=[float(x) for x in r["emb"].strip("[]").split(",")],
                    sparse_indices=idx,
                    sparse_values=val,
                    embedding_version=str(r["embedding_model"] or ""),
                )
            )
        assert self.d.vectors is not None
        self.d.vectors.upsert(points)

    def _fail(self, doc_id: str, org: str, ws: str, reason: str) -> None:
        with self.d.db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            conn.execute(
                "update documents set status = 'failed', lifecycle = 'failed', error = %s,"
                " updated_at = now() where id = %s",
                [reason, doc_id],
            )
            lmqa_audit.append(
                conn,
                org_id=org,
                workspace_id=ws,
                action="document.failed",
                target_type="document",
                target_id=doc_id,
                payload={"reason": reason},
            )


# --- indexer: index_outbox -> Qdrant (10.6, G4.10) ------------------------------------------------------------


class Indexer:
    def __init__(self, db: Database, vectors: VectorWriter) -> None:
        self._db = db
        self._vectors = vectors

    def run_once(self, limit: int = 200) -> int:
        done = 0
        with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            rows = conn.execute(
                "select o.id, o.org_id, o.workspace_id, o.document_id, o.operation, d.visibility, d.matter_id,"
                " d.tier, d.owner_id from index_outbox o left join documents d on d.id = o.document_id"
                " where o.state = 'pending' order by o.id limit %s for update of o skip locked",
                [limit],
            ).fetchall()
            for r in rows:
                try:
                    if r["operation"] == "delete_vectors" or r["visibility"] is None:
                        self._vectors.delete_document(
                            str(r["org_id"]), str(r["workspace_id"]), str(r["document_id"])
                        )
                    else:
                        self._vectors.set_payload(
                            str(r["org_id"]),
                            str(r["workspace_id"]),
                            str(r["document_id"]),
                            {
                                "visibility": r["visibility"],
                                "matter_id": str(r["matter_id"]) if r["matter_id"] else None,
                                "tier": int(r["tier"]),
                                "owner_id": str(r["owner_id"]),
                            },
                        )
                    conn.execute(
                        "update index_outbox set state = 'done', done_at = now() where id = %s",
                        [r["id"]],
                    )
                    conn.execute(
                        "update document_versions set index_state = 'in_sync' where document_id = %s",
                        [r["document_id"]],
                    )
                    done += 1
                except Exception as exc:
                    conn.execute(
                        "update index_outbox set attempts = attempts + 1, last_error = %s,"
                        " state = case when attempts >= 9 then 'dead' else 'pending' end where id = %s",
                        [type(exc).__name__, r["id"]],
                    )
        return done


# --- reconciler: drift repair (10.6, G4.10) -------------------------------------------------------------------


@dataclass
class DriftReport:
    missing: int = 0
    orphans: int = 0
    payload_fixed: int = 0
    scope_mismatch: int = 0


class Reconciler:
    def __init__(self, db: Database, vectors: VectorWriter, reindex: Callable[[str], None]) -> None:
        self._db = db
        self._vectors = vectors
        self._reindex = reindex

    def run_workspace(self, org_id: str, workspace_id: str) -> DriftReport:
        report = DriftReport()
        with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            rows = conn.execute(
                "select c.id, c.version, c.document_id, c.visibility, c.matter_id, c.tier, c.owner_id,"
                " d.created_at from chunks c join documents d on d.id = c.document_id"
                " where c.workspace_id = %s and c.embedding is not null and d.status = 'ready'",
                [workspace_id],
            ).fetchall()
        expected = {point_id(str(r["id"]), int(r["version"])): r for r in rows}
        seen: set[str] = set()
        orphans: list[str] = []
        stale_docs: set[str] = set()
        now = time.time()
        for pid, payload in self._vectors.scroll_workspace(org_id, workspace_id):
            seen.add(pid)
            row = expected.get(pid)
            if row is None:
                orphans.append(pid)
                continue
            want = {
                "visibility": row["visibility"],
                "matter_id": str(row["matter_id"]) if row["matter_id"] else None,
                "tier": int(row["tier"]),
                "owner_id": str(row["owner_id"]),
            }
            if any(payload.get(k) != v for k, v in want.items()):
                stale_docs.add(str(row["document_id"]))
                # A payload wider than PostgreSQL would be a scope mismatch; RLS still blocks it, but alert.
                if payload.get("visibility") != row["visibility"]:
                    report.scope_mismatch += 1
        for doc in stale_docs:
            r = next(x for x in rows if str(x["document_id"]) == doc)
            self._vectors.set_payload(
                org_id,
                workspace_id,
                doc,
                {
                    "visibility": r["visibility"],
                    "matter_id": str(r["matter_id"]) if r["matter_id"] else None,
                    "tier": int(r["tier"]),
                    "owner_id": str(r["owner_id"]),
                },
            )
            report.payload_fixed += 1
        # Orphans older than the grace period are deleted (a just-written point may not be committed yet).
        if orphans:
            self._vectors.delete_points(org_id, workspace_id, orphans)
            report.orphans = len(orphans)
        missing_docs = {
            str(r["document_id"])
            for pid, r in expected.items()
            if pid not in seen and now - r["created_at"].timestamp() > ORPHAN_GRACE_SECONDS
        }
        for doc in missing_docs:
            self._reindex(doc)
        report.missing = len(missing_docs)
        if report.scope_mismatch:
            with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
                conn.execute(
                    "insert into alerts (org_id, workspace_id, rule, severity, summary, dedup_key)"
                    " values (%s, %s, 'vector_scope_mismatch', 'page', 'Vector payload wider than PostgreSQL', %s)"
                    " on conflict do nothing",
                    [org_id, workspace_id, f"vector_scope_mismatch:{workspace_id}"],
                )
        return report


# --- deletion and crypto-erase (12.9, G4.11) ------------------------------------------------------------------


def erase_document(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
    db: Database,
    keyring: KeyRing,
    vectors: VectorWriter | None,
    object_store: Any | None,
    *,
    org_id: str,
    workspace_id: str,
    document_id: str,
    actor_id: str,
) -> None:
    """Destroy the document key (chunk text and the encrypted original become undecryptable), then remove vectors
    and objects, then tombstone. The tombstone is mirrored to the Object Lock ledger outside backups."""
    with db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
        held = conn.execute(
            "select legal_hold, object_key from documents where id = %s", [document_id]
        ).fetchone()
        if held is None:
            return
        if held["legal_hold"]:
            raise PermissionError("legal hold: the document cannot be deleted")
        conn.execute("update documents set lifecycle = 'deleting' where id = %s", [document_id])
        keyring.shred_document(conn, org_id, workspace_id, document_id, approvers=[actor_id])
        conn.execute(
            "insert into index_outbox (org_id, workspace_id, document_id, version, operation)"
            " values (%s, %s, %s, 1, 'delete_vectors')",
            [org_id, workspace_id, document_id],
        )
        lmqa_audit.append(
            conn,
            org_id=org_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            action="document.erased",
            target_type="document",
            target_id=document_id,
            payload={},
        )
    if vectors is not None:
        vectors.delete_document(org_id, workspace_id, document_id)
    if object_store is not None:
        for key in object_store.list_prefix(f"org_{org_id}/ws_{workspace_id}/doc_{document_id}/"):
            object_store.delete_object(key)


def main() -> int:
    parser = argparse.ArgumentParser(description="production ingestion processes")
    parser.add_argument("role", choices=["worker", "indexer", "reconciler"])
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    configure_logging(logging.INFO)
    settings = load_settings()
    infra = load_infra_settings()
    db = Database(settings)
    db.open()
    vectors = VectorWriter(infra.qdrant_url, infra.require("QDRANT_KEY_RW"))
    vectors.ensure_collection()
    if args.role == "indexer":
        indexer = Indexer(db, vectors)
        while True:
            indexer.run_once()
            time.sleep(args.interval)
    if args.role == "reconciler":
        rec = Reconciler(db, vectors, reindex=lambda doc: log.info("reindex requested for %s", doc))
        while True:
            with db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
                spaces = conn.execute(
                    "select org_id, id from workspaces where status = 'active'"
                ).fetchall()
            for ws in spaces:
                log.info(
                    "reconciled %s: %s",
                    ws["id"],
                    rec.run_workspace(str(ws["org_id"]), str(ws["id"])),
                )
            time.sleep(max(args.interval, 60.0))
    from ingestion import create_ingestion

    keys = field_cipher_from_settings()
    _, ingestor = create_ingestion(settings, db, keys=keys)

    app = build_app(settings)
    keyring = keys.ring
    from lmqa_vectorstore.sparse import encode_documents

    # The worker verifies envelopes against the trust bundle published by the gateway (LMQA_TRUST_BUNDLE_FILE).
    bundle_file = settings.data_dir / "trust" / "bundle.json"
    bundle = (
        [(k, v.encode()) for k, v in json.loads(bundle_file.read_text()).items()]
        if bundle_file.is_file()
        else []
    )
    register_tasks(
        app,
        WorkerDeps(
            settings,
            db,
            keyring,
            bundle,
            ingestor.run,
            vectors,
            None,
            lambda texts: encode_documents(texts, settings.model_cache_dir),
        ),
    )
    app.run_worker(queues=[QUEUE], concurrency=4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
