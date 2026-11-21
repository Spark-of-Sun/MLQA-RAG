"""Chats: list, open, rename, delete. Every statement runs under RLS, so a chat is visible only to its author.

A chat is created by its first question (gateway/query_flow.py), so failed first questions never leave empty
chats behind. Deleting a chat deletes its questions and retrieval ledger; the hash-chained audit events, which
hold hashes and IDs only, are kept.
"""

from __future__ import annotations

from typing import Any

import lmqa_audit
from gateway.query_flow import QueryFlow
from lmqa_db import Database
from lmqa_models.errors import BadRequest, NotFound
from lmqa_models.principal import Principal

MAX_TURNS = 100


class Conversations:
    def __init__(self, db: Database, flow: QueryFlow) -> None:
        self._db = db
        self._flow = flow

    def list(self, p: Principal, limit: int = 50) -> list[dict[str, Any]]:
        with self._db.scoped(p.user_id) as scope:
            rows = scope.execute(
                """
                select c.id, c.title, c.created_at, c.updated_at,
                       (select count(*) from queries q where q.conversation_id = c.id) as turns
                from conversations c order by c.updated_at desc limit %s
                """,
                [limit],
            ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
                "turns": r["turns"],
            }
            for r in rows
        ]

    def get(self, p: Principal, conversation_id: str) -> dict[str, Any]:
        with self._db.scoped(p.user_id) as scope:
            conv = scope.execute(
                "select id, title, created_at, updated_at from conversations where id = %s", [conversation_id]
            ).fetchone()
            if conv is None:
                raise NotFound("Chat not found.")
            rows = scope.execute(
                "select * from (select id, conversation_id, question, standalone_question, result, created_at"
                " from queries where conversation_id = %s order by created_at desc limit %s) t order by created_at",
                [conversation_id, MAX_TURNS],
            ).fetchall()
            turns = self._flow.with_current_citations(scope, rows)
        return {
            "id": str(conv["id"]),
            "title": conv["title"],
            "created_at": conv["created_at"].isoformat(),
            "updated_at": conv["updated_at"].isoformat(),
            "turns": turns,
        }

    def rename(self, p: Principal, conversation_id: str, title: str) -> dict[str, Any]:
        m = p.membership
        assert m is not None
        clean = " ".join(title.split())[:200]
        if not clean:
            raise BadRequest("The title cannot be empty.")
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(
                "update conversations set title = %s where id = %s returning id, title", [clean, conversation_id]
            ).fetchone()
            if row is None:
                raise NotFound("Chat not found.")
            # The title is the person's own words; like questions, the audit keeps no text.
            lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="conversation.renamed",
                target_type="conversation",
                target_id=conversation_id,
            )
        return {"id": str(row["id"]), "title": row["title"]}

    def delete(self, p: Principal, conversation_id: str) -> None:
        m = p.membership
        assert m is not None
        with self._db.scoped(p.user_id) as scope:
            turns = scope.execute(
                "select count(*) as n from queries where conversation_id = %s", [conversation_id]
            ).fetchone()
            row = scope.execute("delete from conversations where id = %s returning id", [conversation_id]).fetchone()
            if row is None:
                raise NotFound("Chat not found.")
            lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="conversation.deleted",
                target_type="conversation",
                target_id=conversation_id,
                payload={"turns": turns["n"] if turns else 0},
            )
