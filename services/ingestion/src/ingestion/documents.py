"""Document library API logic: upload, list, get, delete. Every content statement runs under RLS."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any

import psycopg

import lmqa_audit
from ingestion.parsers import ParseError, detect_type
from ingestion.pipeline import Ingestor
from lmqa_db import Database
from lmqa_models.errors import BadRequest, Forbidden, NotFound, TooLarge
from lmqa_models.principal import Principal
from lmqa_models.settings import Settings
from lmqa_objectstore import ObjectStore

COLUMNS = (
    "id, title, filename, file_type, size_bytes, visibility, status, error, notes, page_count, chunk_count,"
    " structure, created_at, updated_at, owner_id"
)


def title_from_filename(filename: str) -> str:
    stem = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return (re.sub(r"_+", " ", stem).strip() or "Untitled document")[:200]


class DocumentService:
    def __init__(self, settings: Settings, db: Database, store: ObjectStore, ingestor: Ingestor) -> None:
        self._s = settings
        self._db = db
        self._store = store
        self._ingestor = ingestor

    def _shape(self, rows: list[dict[str, Any]], p: Principal) -> list[dict[str, Any]]:
        owners: dict[str, str] = {}
        ids = list({str(r["owner_id"]) for r in rows})
        if ids:
            with self._db.system() as conn:
                for r in conn.execute(
                    "select id, coalesce(name, email) as label from users where id = any(%s)", [ids]
                ).fetchall():
                    owners[str(r["id"])] = r["label"] or "User"
        out = []
        for r in rows:
            item = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
            item["id"] = str(r["id"])
            item["owner_id"] = str(r["owner_id"])
            item["owner"] = owners.get(item["owner_id"], "User")
            item["mine"] = item["owner_id"] == p.user_id
            out.append(item)
        return out

    def list(self, p: Principal) -> list[dict[str, Any]]:
        with self._db.scoped(p.user_id) as scope:
            rows = scope.execute(f"select {COLUMNS} from documents order by created_at desc").fetchall()
        return self._shape(rows, p)

    def get(self, p: Principal, doc_id: str) -> dict[str, Any]:
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(f"select {COLUMNS} from documents where id = %s", [doc_id]).fetchone()
        if row is None:
            raise NotFound("Document not found.")
        return self._shape([row], p)[0]

    def upload(
        self,
        p: Principal,
        filename: str,
        data: bytes,
        visibility: str | None,
        title: str | None = None,
    ) -> dict[str, Any]:
        m = p.membership
        assert m is not None and m.workspace_id is not None
        if not data:
            raise BadRequest("The file is empty.")
        if len(data) > self._s.upload_max_mb * 1024 * 1024:
            raise TooLarge(f"Files are limited to {self._s.upload_max_mb} MB.")
        vis = visibility or ("workspace" if m.role == "admin" else "private")
        if vis not in {"workspace", "private"}:
            raise BadRequest("Visibility must be workspace or private.")
        if vis == "workspace" and m.role != "admin":
            raise Forbidden("Only the workspace admin can share documents with the whole workspace.")
        try:
            kind = detect_type(filename, data)
        except ParseError as exc:
            raise BadRequest(str(exc)) from exc
        digest = hashlib.sha256(data).hexdigest()
        clean_title = " ".join((title or title_from_filename(filename)).split())[:200] or "Untitled document"
        doc_id = str(uuid.uuid4())
        key = ObjectStore.key(m.org_id, m.workspace_id, doc_id, kind)
        self._store.put(key, data)
        try:
            with self._db.scoped(p.user_id) as scope:
                row = scope.execute(
                    "insert into documents (id, org_id, workspace_id, owner_id, title, filename, file_type,"
                    " size_bytes, sha256, object_key, visibility)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    f" returning {COLUMNS}",
                    [
                        doc_id,
                        m.org_id,
                        m.workspace_id,
                        p.user_id,
                        clean_title,
                        filename[-255:],
                        kind,
                        len(data),
                        digest,
                        key,
                        vis,
                    ],
                ).fetchone()
                assert row is not None
                lmqa_audit.append(
                    scope,
                    org_id=m.org_id,
                    workspace_id=m.workspace_id,
                    actor_id=p.user_id,
                    action="document.uploaded",
                    target_type="document",
                    target_id=doc_id,
                    payload={
                        "title": clean_title,
                        "type": kind,
                        "bytes": len(data),
                        "sha256": digest,
                        "visibility": vis,
                    },
                )
        except psycopg.errors.InsufficientPrivilege as exc:
            self._store.delete(key)
            raise Forbidden("You are not allowed to add this document.") from exc
        except BaseException:
            self._store.delete(key)
            raise
        self._ingestor.submit(doc_id)
        return self._shape([row], p)[0]

    def delete(self, p: Principal, doc_id: str) -> None:
        with self._db.scoped(p.user_id) as scope:
            if scope.execute("select 1 from documents where id = %s", [doc_id]).fetchone() is None:
                raise NotFound("Document not found.")
            row = scope.execute(
                "delete from documents where id = %s returning org_id, workspace_id, object_key, title", [doc_id]
            ).fetchone()
            if row is None:
                raise Forbidden("Only the owner or the workspace admin can delete this document.")
            lmqa_audit.append(
                scope,
                org_id=row["org_id"],
                workspace_id=row["workspace_id"],
                actor_id=p.user_id,
                action="document.deleted",
                target_type="document",
                target_id=doc_id,
                payload={"title": row["title"]},
            )
        self._store.delete(row["object_key"])
