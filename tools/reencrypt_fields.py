"""One-time re-encryption of plaintext columns (KD-9; R-51 criterion 3; DEV-09 columns; Q-36 default).

    make reencrypt                     # the configured database (LMQA_DB_NAME)
    python tools/reencrypt_fields.py --database NAME

`make migrate` runs this between 0012_field_encryption (adds the ciphertext columns) and 0013_drop_plaintext (drops
the plaintext ones), so it normally never needs to be called by hand. It:

1. provisions keys: the organization CMK (OpenBao Transit locally, AWS KMS in the cloud) and a workspace content key
   for every organization and workspace, the workspace-month audit key pairs (and the organization control chain's)
   for this month and the next, and the platform contact and blind-index keys;
2. creates a document key for every document that has none;
3. fills every missing ciphertext column from its plaintext column, in batches, one transaction per batch:
   documents (title, filename), chunks (text, section), queries (question, standalone question, result),
   query_segments (text), conversations (title), users (email, name, phone and the email blind index).

Idempotent: only rows whose ciphertext is still null are touched, and keys that exist are reused, so a run that
stops halfway is finished by the next one. After 0013 the plaintext columns are gone and only step 1 runs.

It connects as the local superuser, like the role bootstrap in `lmqa_db.migrate`: a migration has to see every
workspace's rows, which no runtime role can (every runtime role is NOBYPASSRLS). Values and keys are never printed;
the report names tables and counts only.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, LiteralString

import psycopg
from psycopg.rows import dict_row

from lmqa_db import connect_role
from lmqa_keys import Field, FieldCipher, KeyRing, provider_from_settings
from lmqa_models.settings import Settings, load_settings

BATCH = 500
Conn = psycopg.Connection[dict[str, Any]]


def _columns(conn: Conn, table: str) -> set[str]:
    rows = conn.execute(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = %s",
        [table],
    ).fetchall()
    return {r["column_name"] for r in rows}


def plaintext_remaining(conn: Conn) -> dict[str, int]:
    """table -> rows that still need ciphertext. Empty once 0013 has dropped the plaintext columns."""
    checks: dict[str, tuple[str, LiteralString]] = {
        "documents": (
            "title",
            "select count(*) as n from documents where title_ct is null or filename_ct is null",
        ),
        "chunks": (
            "text",
            "select count(*) as n from chunks"
            " where text_ct is null or (section is not null and section_ct is null)",
        ),
        "queries": (
            "question",
            "select count(*) as n from queries where question_ct is null or result_ct is null"
            " or (standalone_question is not null and standalone_question_ct is null)",
        ),
        "query_segments": (
            "text",
            "select count(*) as n from query_segments where text is not null and text_ct is null",
        ),
        "conversations": (
            "title",
            "select count(*) as n from conversations where title_ct is null",
        ),
        "users": (
            "email",
            "select count(*) as n from users where (email is not null and email_ct is null)"
            " or (name is not null and name_ct is null) or (phone is not null and phone_ct is null)",
        ),
    }
    out: dict[str, int] = {}
    for table, (plain, query) in checks.items():
        if plain in _columns(conn, table):
            n = conn.execute(query).fetchone()
            if n and n["n"]:
                out[table] = int(n["n"])
    return out


def _months(today: date) -> list[date]:
    this = date(today.year, today.month, 1)
    following = date(this.year + (this.month == 12), this.month % 12 + 1, 1)
    return [this, following]


def provision(conn: Conn, ring: KeyRing, *, today: date | None = None) -> dict[str, int]:
    """Keys for every organization and workspace (idempotent). Returns counts by kind."""
    months = _months(today or datetime.now(UTC).date())
    counts = {"organizations": 0, "workspaces": 0, "audit_keys": 0, "documents": 0}
    for org in conn.execute("select id from organizations order by created_at").fetchall():
        ring.ensure_org_key(conn, org["id"])
        for month in months:
            ring.ensure_audit_key(conn, org["id"], None, month)
            counts["audit_keys"] += 1
        counts["organizations"] += 1
        conn.commit()
    for ws in conn.execute("select org_id, id from workspaces order by created_at").fetchall():
        ring.ensure_workspace_key(conn, ws["org_id"], ws["id"])
        for month in months:
            ring.ensure_audit_key(conn, ws["org_id"], ws["id"], month)
            counts["audit_keys"] += 1
        counts["workspaces"] += 1
        conn.commit()
    if conn.execute("select 1 from users limit 1").fetchone():
        for purpose in ("contact", "blind_index"):
            ring.ensure_platform_key(conn, purpose)
        conn.commit()
    for doc in conn.execute(
        "select d.org_id, d.workspace_id, d.id from documents d"
        " where not exists (select 1 from doc_keys k where k.document_id = d.id)"
    ).fetchall():
        ring.create_document_key(conn, doc["org_id"], doc["workspace_id"], doc["id"])
        counts["documents"] += 1
    conn.commit()
    return counts


Update = tuple[LiteralString, list[Any]]


def _batches(conn: Conn, select: LiteralString, update: Callable[[dict[str, Any]], Update]) -> int:
    done = 0
    while True:
        rows = conn.execute(select + " limit %s", [BATCH]).fetchall()
        if not rows:
            return done
        for row in rows:
            conn.execute(*update(row))
        conn.commit()
        done += len(rows)


def reencrypt(conn: Conn, cipher: FieldCipher) -> dict[str, int]:
    """Fill every missing ciphertext column. Returns rows re-encrypted per table."""
    if not plaintext_remaining(conn):
        return {}
    out: dict[str, int] = {}

    def document(row: dict[str, Any]) -> Update:
        scope = (row["org_id"], row["workspace_id"], row["id"])
        return (
            "update documents set title_ct = %s, filename_ct = %s where id = %s",
            [
                cipher.seal(conn, Field.document("document.title", *scope), row["title"]),
                cipher.seal(conn, Field.document("document.filename", *scope), row["filename"]),
                row["id"],
            ],
        )

    out["documents"] = _batches(
        conn,
        "select id, org_id, workspace_id, title, filename from documents"
        " where title_ct is null or filename_ct is null",
        document,
    )

    def chunk(row: dict[str, Any]) -> Update:
        args = (row["org_id"], row["workspace_id"], row["document_id"], row["id"], row["version"])
        return (
            "update chunks set text_ct = %s, section_ct = %s where id = %s",
            [
                cipher.seal(conn, Field.chunk("chunk.text", *args), row["text"]),
                cipher.seal(conn, Field.chunk("chunk.section", *args), row["section"]),
                row["id"],
            ],
        )

    out["chunks"] = _batches(
        conn,
        "select id, org_id, workspace_id, document_id, version, text, section from chunks"
        " where text_ct is null or (section is not null and section_ct is null)",
        chunk,
    )

    def query(row: dict[str, Any]) -> Update:
        def field(purpose: str) -> Field:
            return Field.workspace(purpose, row["org_id"], row["workspace_id"], row["id"])

        return (
            "update queries set question_ct = %s, standalone_question_ct = %s, result_ct = %s where id = %s",
            [
                cipher.seal(conn, field("query.question"), row["question"]),
                cipher.seal(conn, field("query.standalone_question"), row["standalone_question"]),
                cipher.seal_json(conn, field("query.result"), row["result"] or {}),
                row["id"],
            ],
        )

    out["queries"] = _batches(
        conn,
        "select id, org_id, workspace_id, question, standalone_question, result from queries"
        " where question_ct is null or result_ct is null"
        " or (standalone_question is not null and standalone_question_ct is null)",
        query,
    )

    def segment(row: dict[str, Any]) -> Update:
        field = Field.workspace(
            "segment.text", row["org_id"], row["workspace_id"], f"{row['query_id']}:{row['seq']}"
        )
        return (
            "update query_segments set text_ct = %s where query_id = %s and seq = %s",
            [cipher.seal(conn, field, row["text"]), row["query_id"], row["seq"]],
        )

    out["query_segments"] = _batches(
        conn,
        "select query_id, seq, org_id, workspace_id, text from query_segments"
        " where text is not null and text_ct is null",
        segment,
    )

    def conversation(row: dict[str, Any]) -> Update:
        field = Field.workspace("conversation.title", row["org_id"], row["workspace_id"], row["id"])
        return (
            "update conversations set title_ct = %s where id = %s",
            [cipher.seal(conn, field, row["title"]), row["id"]],
        )

    out["conversations"] = _batches(
        conn,
        "select id, org_id, workspace_id, title from conversations where title_ct is null",
        conversation,
    )

    def user(row: dict[str, Any]) -> Update:
        return (
            "update users set email_ct = %s, name_ct = %s, phone_ct = %s, email_blind_index = %s where id = %s",
            [
                cipher.seal(conn, Field.contact("user.email", row["id"]), row["email"]),
                cipher.seal(conn, Field.contact("user.name", row["id"]), row["name"]),
                cipher.seal(conn, Field.contact("user.phone", row["id"]), row["phone"]),
                cipher.blind_index(conn, row["email"]),
                row["id"],
            ],
        )

    out["users"] = _batches(
        conn,
        "select id, email, name, phone from users where (email is not null and email_ct is null)"
        " or (name is not null and name_ct is null) or (phone is not null and phone_ct is null)",
        user,
    )
    return {k: v for k, v in out.items() if v}


def run(settings: Settings, database: str | None = None) -> dict[str, Any]:
    """Provision keys and re-encrypt; returns a report of counts (no values)."""
    db = database or settings.db_name
    with connect_role(settings, "postgres", database=db, row_factory=dict_row) as conn:
        empty = not conn.execute(
            "select 1 from organizations union all select 1 from users limit 1"
        ).fetchone()
        if empty:
            return {"database": db, "keys": {}, "reencrypted": {}}
        ring = KeyRing(provider_from_settings())
        cipher = FieldCipher(ring)
        keys = provision(conn, ring)
        rows = reencrypt(conn, cipher)
        left = plaintext_remaining(conn)
    if left:
        raise RuntimeError(f"re-encryption incomplete: {left}")
    return {"database": db, "keys": keys, "reencrypted": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time re-encryption of plaintext columns")
    parser.add_argument("--database", help="database name (default: LMQA_DB_NAME)")
    args = parser.parse_args()
    report = run(load_settings(), args.database)
    print(
        f"database {report['database']}: keys {report['keys']}; "
        f"re-encrypted {report['reencrypted'] or 'nothing (no plaintext rows)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
