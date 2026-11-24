"""Document library API logic: upload, list, get, delete. Every content statement runs under RLS.

Access to a document (blueprint 5.4, MVP subset):
  workspace  the admin shared it with everyone in the workspace
  shared     the owner shared it with named people: a member with their admin, the admin with chosen members
  private    the owner only
Shares are rows in `document_shares`, inserted in the same transaction as the document and checked by RLS.

`workspace` visibility (MVP rule 7a) and named shares (rule 7b) are frozen MVP-only features (DEV-14, DEV-21, flags
`workspace_visibility` and `named_shares`, pending Q-04 and Q-05). While a flag is off no upload can create such a
document or share, and no code path here reads `document_shares`. Neither rule is part of `app_can_read` any more
(0011_access_rules): existing `workspace` documents reverted to `private` (Q-37 default), the database refuses the
`workspace` value, and a share row grants nothing.
"""

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
from lmqa_db import Claims, Database, Scope
from lmqa_keys import Field, FieldCipher
from lmqa_models.contracts import feature_enabled
from lmqa_models.errors import BadRequest, Forbidden, NotFound, TooLarge
from lmqa_models.principal import Principal
from lmqa_models.settings import Settings
from lmqa_objectstore import ObjectStore

# title and filename are stored sealed with the document key (title_ct, filename_ct; lmqa_keys, R-51.3).
COLUMNS = (
    "id, org_id, workspace_id, title_ct, filename_ct, file_type, size_bytes, visibility, status, error, notes,"
    " page_count, chunk_count, structure, created_at, updated_at, owner_id"
)
SHARE_ADMIN = "admin"  # what a member sends to mean "my workspace admin"; resolved here, never trusted as an ID
MAX_SHARES = 200


def title_from_filename(filename: str) -> str:
    stem = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return (re.sub(r"_+", " ", stem).strip() or "Untitled document")[:200]


def upload_visibility(role: str, visibility: str | None, share_with: list[str]) -> str:
    """The visibility of a new document, checked before anything is stored. Frozen features are refused."""
    named = any(s and s.strip() for s in share_with)
    if named and not feature_enabled("named_shares"):
        raise BadRequest("Documents cannot be shared with named people.")
    workspace_on = feature_enabled("workspace_visibility")
    vis = visibility or (
        "workspace" if role == "admin" and workspace_on and not named else "private"
    )
    if vis not in ({"workspace", "private"} if workspace_on else {"private"}):
        raise BadRequest(
            "Visibility must be workspace or private."
            if workspace_on
            else "Visibility must be private."
        )
    if vis == "workspace" and role != "admin":
        raise Forbidden("Only the workspace admin can share documents with the whole workspace.")
    return vis


def shares_of(conn: psycopg.Connection[Any] | Scope, doc_ids: list[str]) -> dict[str, list[str]]:
    """document_id -> recipient user IDs, as visible to the connection (owner: all; recipient: themself). Empty,
    without reading `document_shares`, while the frozen `named_shares` feature is off."""
    out: dict[str, list[str]] = {}
    if doc_ids and feature_enabled("named_shares"):
        rows = conn.execute(
            "select document_id, user_id from document_shares where document_id = any(%s) order by created_at",
            [doc_ids],
        ).fetchall()
        for r in rows:
            out.setdefault(str(r["document_id"]), []).append(str(r["user_id"]))
    return out


def open_document(keys: FieldCipher, conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """A documents row with title and filename decrypted; the ciphertext and scope columns removed."""
    item = dict(row)
    scope = (item.pop("org_id"), item.pop("workspace_id"), item["id"])
    item["title"] = keys.open(conn, Field.document("document.title", *scope), item.pop("title_ct"))
    item["filename"] = keys.open(
        conn, Field.document("document.filename", *scope), item.pop("filename_ct")
    )
    return item


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        store: ObjectStore,
        ingestor: Ingestor,
        keys: FieldCipher,
    ) -> None:
        self._s = settings
        self._db = db
        self._store = store
        self._ingestor = ingestor
        self._keys = keys

    def _shape(
        self, rows: list[dict[str, Any]], shares: dict[str, list[str]], p: Principal
    ) -> list[dict[str, Any]]:
        m = p.membership
        assert m is not None
        people: dict[str, dict[str, Any]] = {}
        ids = list({str(r["owner_id"]) for r in rows} | {u for us in shares.values() for u in us})
        if ids:
            # Names and emails are sealed (R-51.3); app_workspace_people (17_ingestion.sql) returns them only for
            # members of the caller's workspace.
            with self._db.as_service("ingestion", Claims(user_id=uuid.UUID(p.user_id))) as conn:
                for r in conn.execute(
                    "select id, name_ct, email_ct, role from app_workspace_people(%s::uuid[])",
                    [ids],
                ).fetchall():
                    person = self._keys.open_contact_row(conn, dict(r))
                    people[str(r["id"])] = {
                        "label": person["name"] or person["email"] or "User",
                        "role": r["role"] or "tenant",
                    }
        out = []
        for r in rows:
            item = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
            doc_id, owner_id = str(r["id"]), str(r["owner_id"])
            owner = people.get(owner_id, {"label": "User", "role": "tenant"})
            mine = owner_id == p.user_id
            recipients = shares.get(doc_id, [])
            access = (
                "workspace"
                if r["visibility"] == "workspace"
                else "shared"
                if recipients
                else "private"
            )
            item.update(
                {
                    "id": doc_id,
                    "owner_id": owner_id,
                    "owner": owner["label"],
                    "owner_role": owner["role"],
                    "mine": mine,
                    "access": access,
                    "shared_by": None
                    if access == "private"
                    else "you"
                    if mine
                    else ("admin" if owner["role"] == "admin" else "member"),
                    "shared_with": [
                        {
                            "id": u,
                            "name": people.get(u, {}).get("label", "User"),
                            "role": people.get(u, {}).get("role", "tenant"),
                        }
                        for u in recipients
                    ],
                }
            )
            out.append(item)
        return out

    def list(self, p: Principal) -> list[dict[str, Any]]:
        with self._db.scoped(p.user_id) as scope:
            rows = [
                open_document(self._keys, scope, r)
                for r in scope.execute(
                    f"select {COLUMNS} from documents order by created_at desc"  # noqa: S608 - COLUMNS is a module constant; values bound
                ).fetchall()
            ]
            shares = shares_of(scope, [str(r["id"]) for r in rows])
        return self._shape(rows, shares, p)

    def get(self, p: Principal, doc_id: str) -> dict[str, Any]:
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(
                f"select {COLUMNS} from documents where id = %s",  # noqa: S608 - COLUMNS is a constant
                [doc_id],
            ).fetchone()
            if row is None:
                raise NotFound("Document not found.")
            row = open_document(self._keys, scope, row)
            shares = shares_of(scope, [doc_id])
        return self._shape([row], shares, p)[0]

    def _resolve_recipients(self, p: Principal, vis: str, share_with: list[str]) -> list[str]:
        """Turn the requested recipients into user IDs, with friendly errors. RLS re-checks every row."""
        m = p.membership
        assert m is not None
        wanted = list(dict.fromkeys(s.strip() for s in share_with if s and s.strip()))
        if not wanted:
            return []
        if vis == "workspace":
            raise BadRequest(
                "A document shared with the whole workspace cannot also have individual shares."
            )
        if len(wanted) > MAX_SHARES:
            raise BadRequest(f"Share with at most {MAX_SHARES} people at once.")
        with self._db.as_service("ingestion", Claims(actor="ingestion:worker")) as conn:
            if m.role == "tenant":
                if wanted != [SHARE_ADMIN]:
                    raise Forbidden(
                        "Members can share their documents with their workspace admin only."
                    )
                admin = conn.execute(
                    "select user_id from memberships where workspace_id = %s and role = 'admin' and status = 'active'",
                    [m.workspace_id],
                ).fetchone()
                if admin is None:
                    raise BadRequest("Your workspace has no active admin to share with.")
                return [str(admin["user_id"])]
            try:
                ids = [str(uuid.UUID(s)) for s in wanted]
            except ValueError as exc:
                raise BadRequest("Choose members of your workspace to share with.") from exc
            found = conn.execute(
                "select user_id from memberships where workspace_id = %s and role = 'tenant' and status = 'active'"
                " and user_id = any(%s)",
                [m.workspace_id, ids],
            ).fetchall()
        if len(found) != len(ids):
            raise BadRequest("Choose active members of your workspace to share with.")
        return ids

    def upload(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        filename: str,
        data: bytes,
        visibility: str | None,
        title: str | None = None,
        share_with: list[str] | None = None,
    ) -> dict[str, Any]:
        m = p.membership
        assert m is not None and m.workspace_id is not None
        if not data:
            raise BadRequest("The file is empty.")
        if len(data) > self._s.upload_max_mb * 1024 * 1024:
            raise TooLarge(f"Files are limited to {self._s.upload_max_mb} MB.")
        vis = upload_visibility(m.role, visibility, share_with or [])
        recipients = self._resolve_recipients(p, vis, share_with or [])
        try:
            kind = detect_type(filename, data)
        except ParseError as exc:
            raise BadRequest(str(exc)) from exc
        digest = hashlib.sha256(data).hexdigest()
        clean_title = (
            " ".join((title or title_from_filename(filename)).split())[:200] or "Untitled document"
        )
        doc_id = str(uuid.uuid4())
        key = ObjectStore.key(m.org_id, m.workspace_id, doc_id, kind)
        self._store.put(key, data)
        try:
            with self._db.scoped(p.user_id) as scope:
                # The document key first: the title and file name are sealed with it in this transaction.
                self._keys.new_document(scope, m.org_id, m.workspace_id, doc_id)
                doc_scope = (m.org_id, m.workspace_id, doc_id)
                row = scope.execute(
                    "insert into documents (id, org_id, workspace_id, owner_id, title_ct, filename_ct, file_type,"  # noqa: S608 - COLUMNS is a module constant; values bound
                    " size_bytes, sha256, object_key, visibility)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    f" returning {COLUMNS}",
                    [
                        doc_id,
                        m.org_id,
                        m.workspace_id,
                        p.user_id,
                        self._keys.seal(
                            scope, Field.document("document.title", *doc_scope), clean_title
                        ),
                        self._keys.seal(
                            scope, Field.document("document.filename", *doc_scope), filename[-255:]
                        ),
                        kind,
                        len(data),
                        digest,
                        key,
                        vis,
                    ],
                ).fetchone()
                assert row is not None
                row = open_document(self._keys, scope, row)
                if recipients:
                    with scope.cursor() as cur:
                        cur.executemany(
                            "insert into document_shares (org_id, workspace_id, document_id, owner_id, user_id)"
                            " values (%s, %s, %s, %s, %s)",
                            [(m.org_id, m.workspace_id, doc_id, p.user_id, u) for u in recipients],
                        )
                lmqa_audit.append(
                    scope,
                    org_id=m.org_id,
                    workspace_id=m.workspace_id,
                    actor_id=p.user_id,
                    action="document.uploaded",
                    target_type="document",
                    target_id=doc_id,
                    payload={
                        "type": kind,
                        "bytes": len(data),
                        "sha256": digest,
                        "visibility": vis,
                        "shared_with": recipients,
                    },
                )
        except psycopg.errors.InsufficientPrivilege as exc:
            self._store.delete(key)
            raise Forbidden("You are not allowed to add or share this document.") from exc
        except BaseException:
            self._store.delete(key)
            raise
        self._ingestor.submit(doc_id)
        return self._shape([row], {doc_id: recipients}, p)[0]

    def delete(self, p: Principal, doc_id: str) -> None:
        with self._db.scoped(p.user_id) as scope:
            if scope.execute("select 1 from documents where id = %s", [doc_id]).fetchone() is None:
                raise NotFound("Document not found.")
            recipients = shares_of(scope, [doc_id]).get(doc_id, [])
            row = scope.execute(
                "delete from documents where id = %s returning org_id, workspace_id, object_key, visibility",
                [doc_id],
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
                payload={
                    "visibility": row["visibility"],
                    "shared_with": recipients,
                },
            )
        self._store.delete(row["object_key"])
