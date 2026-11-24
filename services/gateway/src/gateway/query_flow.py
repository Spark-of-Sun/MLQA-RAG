"""Conversational, gated query release (blueprint 11.3 to 11.6).

  load the conversation (RLS: only the author can see it) -> plan the search (standalone question for a follow-up,
  alternative phrasings) -> multi-stage retrieval (hybrid search, re-ranking, relevance threshold, neighbours; RLS,
  aliases; the previous turn's cited passages stay available) -> generation draft (earlier
  turns are context only, never a source) -> citation validator (deterministic V1-V8) -> entailment (can only
  remove) -> V3 re-read of chunk hashes under RLS
  -> ONE transaction: chat (created on its first question) + query row + retrieval ledger + audit event
  -> commit -> only then release.

A sentence that fails any check never reaches the client; the client sees a visible "could not be verified"
marker. If any step fails, nothing is released and no chat is created (fail closed).

Chats and LLM query planning are frozen MVP-only features (DEV-21, flag `chats`, pending Q-04 and Q-39): while the
flag is off every question stands alone (no history, no planning call, no chat row, `conversation_id` null) and a
request naming a chat gets 404.

Questions, standalone questions, results and chat titles are stored sealed with the workspace content key
(question_ct, standalone_question_ct, result_ct, title_ct; lmqa_keys, R-51.3). Row IDs are chosen here, before the
insert, because each value's associated data names its row.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

import psycopg

import lmqa_audit
from citation_validator import (
    apply_entailment,
    build_result,
    entailment_claims,
    recheck_integrity,
    validate,
)
from generation import GenerationService, LLMError, Turn
from lmqa_db import Database, Scope
from lmqa_keys import Field, FieldCipher
from lmqa_models.contracts import feature_enabled
from lmqa_models.errors import BadRequest, NotFound, Unavailable
from lmqa_models.principal import Principal
from lmqa_models.quota import question as quota_question
from lmqa_models.quota import rotate
from lmqa_models.rag import Dropped, Source
from lmqa_models.settings import Settings
from retrieval import EmbeddingError, RetrievalService

RETRIEVAL_HEADROOM_TOKENS = 1500
HISTORY_TURNS = 4


def released_text(result: dict[str, Any]) -> str:
    """What the user actually saw: verified sentences and the refusal, never removed claims."""
    return " ".join(
        s["text"] for s in result.get("segments", []) if s.get("type") in {"sentence", "refusal"}
    )


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


QUERY_COLUMNS = "id, org_id, workspace_id, conversation_id, question_ct, standalone_question_ct, result_ct, created_at"


def open_query(keys: FieldCipher, scope: Any, row: dict[str, Any]) -> dict[str, Any]:
    """A queries row with question, standalone_question and result decrypted (ciphertext columns removed)."""
    item = dict(row)

    def field(purpose: str) -> Field:
        return Field.workspace(purpose, item["org_id"], item["workspace_id"], item["id"])

    item["question"] = keys.open(scope, field("query.question"), item.pop("question_ct"))
    item["standalone_question"] = keys.open(
        scope, field("query.standalone_question"), item.pop("standalone_question_ct", None)
    )
    item["result"] = keys.open_json(scope, field("query.result"), item.pop("result_ct")) or {}
    return item


def open_conversation(keys: FieldCipher, scope: Any, row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["title"] = keys.open(
        scope,
        Field.workspace("conversation.title", item["org_id"], item["workspace_id"], item["id"]),
        item.pop("title_ct"),
    )
    return item


def chat_title(question: str) -> str:
    q = " ".join(question.split())
    if len(q) <= 60:
        return q
    cut = q.rfind(" ", 0, 60)
    return q[: cut if cut > 30 else 60].rstrip(" ,;:") + "…"


class QueryFlow:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        retrieval: RetrievalService,
        generation: GenerationService,
        keys: FieldCipher,
    ) -> None:
        self._s = settings
        self._db = db
        self._retrieval = retrieval
        self._generation = generation
        self.keys = keys

    # ------------------------------------------------------------------ ask
    def ask(
        self, p: Principal, question: str, conversation_id: str | None = None
    ) -> dict[str, Any]:
        # Each question gets the next number of the persistent counter; all its model and embedding calls start on
        # that number's key (question 1 the first key, question 2 the second, ...), then the others in order.
        with quota_question(self._s.quota()) as n:
            return self._ask(p, question, conversation_id, n)

    def _ask(  # noqa: C901, PLR0912, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
        self, p: Principal, question: str, conversation_id: str | None, number: int
    ) -> dict[str, Any]:
        started = time.monotonic()
        q = " ".join(question.split())
        if not 3 <= len(q) <= 2000:
            raise BadRequest("Ask a question between 3 and 2,000 characters.")

        history: list[Turn] = []
        carry: list[str] = []
        if conversation_id and not feature_enabled("chats"):
            # Frozen MVP-only feature (DEV-21): with `chats` off a chat is as absent as an unlisted route.
            raise NotFound("Chat not found.")
        if conversation_id:
            with self._db.scoped(p.user_id) as scope:
                if (
                    scope.execute(
                        "select 1 from conversations where id = %s", [conversation_id]
                    ).fetchone()
                    is None
                ):
                    raise NotFound("Chat not found.")
                rows = [
                    open_query(self.keys, scope, r)
                    for r in scope.execute(
                        f"select {QUERY_COLUMNS} from queries where conversation_id = %s"  # noqa: S608 - constant
                        " order by created_at desc limit %s",
                        [conversation_id, HISTORY_TURNS],
                    ).fetchall()
                ]
            rows.reverse()
            history = [Turn(r["question"], released_text(r["result"])) for r in rows]
            if rows:
                carry = [c["chunk_id"] for c in rows[-1]["result"].get("citations", [])]

        timings: dict[str, int] = {}
        t = time.monotonic()
        plan = self._generation.plan_query(history, q, expand=self._s.query_expansion)
        standalone, tokens_in, tokens_out = plan.question, plan.tokens_in, plan.tokens_out
        timings["plan_ms"] = _ms(t)
        # Which model and key (by fingerprint) served each step, so usage can be traced to a project.
        calls: dict[str, str] = {}
        if keys := self._s.gemini_keys():
            calls["question"] = f"#{number} · starts on key {rotate(keys, number)[0][0]}"
        if plan.model:
            calls["plan"] = f"{plan.model} · key {plan.key_id}"
        try:
            found = self._retrieval.retrieve(
                p,
                standalone,
                alternatives=plan.alternatives,
                budget_tokens=self._s.context_budget_tokens - RETRIEVAL_HEADROOM_TOKENS,
                carry_chunk_ids=carry,
            )
        except EmbeddingError as exc:
            raise Unavailable(f"No answer was released: {exc}") from exc
        sources, dropped = found.sources, found.dropped
        retrieval_stats = {**found.stats, "alternatives": plan.alternatives}
        if plan.detail_note:
            retrieval_stats["detail_note"] = plan.detail_note

        ledger: dict[str, Source] = {}
        answerable, verdicts = False, []
        model, prompt_sha = self._generation.client.model, None
        if sources:
            try:
                t = time.monotonic()
                draft = self._generation.draft(
                    q, sources, history=history, standalone=standalone, detail_note=plan.detail_note
                )
                timings["draft_ms"] = _ms(t)
                calls["draft"] = f"{draft.model} · key {draft.key_id}"
                t = time.monotonic()
                ledger = {s.alias: s for s in draft.sources}
                dropped += [Dropped(cid, "token_budget", 0.0) for cid in draft.dropped_for_budget]
                tokens_in, tokens_out = tokens_in + draft.tokens_in, tokens_out + draft.tokens_out
                model, prompt_sha = draft.model, draft.prompt_sha256
                answerable, verdicts = validate(
                    draft.data, ledger, entailment=self._s.verify_entailment
                )
                if self._s.verify_entailment:
                    check = self._generation.entailment(entailment_claims(verdicts), ledger)
                    apply_entailment(verdicts, check.verdicts)
                    if check.model:
                        calls["verify"] = f"{check.model} · key {check.key_id}"
                    tokens_in, tokens_out = (
                        tokens_in + check.tokens_in,
                        tokens_out + check.tokens_out,
                    )
                timings["verify_ms"] = _ms(t)
            except LLMError as exc:
                raise Unavailable(f"No answer was released: {exc}") from exc
        try:
            return self._release(
                p,
                q,
                standalone,
                conversation_id,
                ledger,
                dropped,
                answerable,
                verdicts,
                model,
                prompt_sha,
                tokens_in,
                tokens_out,
                started,
                {**retrieval_stats, **timings, "calls": calls},
            )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise NotFound("This chat was deleted while the answer was being prepared.") from exc

    def _release(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        question: str,
        standalone: str,
        conversation_id: str | None,
        ledger: dict[str, Source],
        dropped: list[Dropped],
        answerable: bool,
        verdicts: list[Any],
        model: str,
        prompt_sha: str | None,
        tokens_in: int,
        tokens_out: int,
        started: float,
        pipeline: dict[str, Any],
    ) -> dict[str, Any]:
        m = p.membership
        assert m is not None
        with self._db.scoped(p.user_id) as scope:
            current = self._retrieval.current_chunks(scope, [s.chunk_id for s in ledger.values()])
            recheck_integrity(verdicts, ledger, {cid: sha for cid, (_, sha) in current.items()})
            result = build_result(answerable, verdicts, ledger)
            latency = int((time.monotonic() - started) * 1000)
            result["stats"].update(
                {
                    "sources_considered": len(ledger),
                    "latency_ms": latency,
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "pipeline": pipeline,
                }
            )
            result["standalone_question"] = standalone
            # Frozen MVP-only feature (DEV-21): with `chats` off a question stands alone and
            # queries.conversation_id stays null.
            conv = (
                self._chat_row(scope, p, question, conversation_id)
                if feature_enabled("chats")
                else None
            )
            conv_id = str(conv["id"]) if conv is not None else None
            qid = str(uuid.uuid7())

            def field(purpose: str) -> Field:
                return Field.workspace(purpose, m.org_id, m.workspace_id, qid)

            row = scope.execute(
                "insert into queries (id, org_id, workspace_id, user_id, conversation_id, question_ct,"
                " standalone_question_ct, outcome, result_ct, model, prompt_sha256, tokens_in, tokens_out,"
                " latency_ms) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " returning id, created_at",
                [
                    qid,
                    m.org_id,
                    m.workspace_id,
                    p.user_id,
                    conv_id,
                    self.keys.seal(scope, field("query.question"), question),
                    self.keys.seal(scope, field("query.standalone_question"), standalone),
                    result["outcome"],
                    self.keys.seal_json(scope, field("query.result"), result),
                    model,
                    prompt_sha,
                    tokens_in,
                    tokens_out,
                    latency,
                ],
            ).fetchone()
            assert row is not None
            query_id = str(row["id"])
            self._retrieval.record_ledger(scope, query_id, list(ledger.values()))
            lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="query.answered",
                target_type="query",
                target_id=query_id,
                payload={
                    "conversation_id": conv_id,
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "released_sha256": hashlib.sha256(released_text(result).encode()).hexdigest(),
                    "outcome": result["outcome"],
                    "verified": result["stats"]["verified"],
                    "removed": result["stats"]["removed"],
                    "chunks": [s.chunk_id for s in ledger.values()],
                    "dropped": [{"chunk_id": d.chunk_id, "reason": d.reason} for d in dropped[:20]],
                    "prompt_sha256": prompt_sha,
                    "model": model,
                    "retrieval": {
                        k: v
                        for k, v in pipeline.items()
                        if k not in {"alternatives", "detail_note"}
                    },
                },
            )
        # Committed: chat, query, ledger and audit event. Only now is anything released.
        texts = {s.chunk_id: s.text for s in ledger.values()}
        for c in result["citations"]:
            c["text"] = texts[c["chunk_id"]]
        result.update(
            {
                "id": query_id,
                "question": question,
                "created_at": row["created_at"].isoformat(),
                "conversation_id": conv_id,
                "conversation_title": conv["title"] if conv is not None else None,
            }
        )
        return result

    def _chat_row(
        self, scope: Scope, p: Principal, question: str, conversation_id: str | None
    ) -> dict[str, Any]:
        """The chat this question belongs to: created by its first question, otherwise touched (`chats` only)."""
        m = p.membership
        assert m is not None
        if conversation_id is not None:
            conv = scope.execute(
                "update conversations set updated_at = now() where id = %s"
                " returning id, org_id, workspace_id, title_ct",
                [conversation_id],
            ).fetchone()
            if conv is None:
                raise NotFound("Chat not found.")
            return open_conversation(self.keys, scope, conv)
        conv_id = str(uuid.uuid4())
        title = chat_title(question)
        conv = scope.execute(
            "insert into conversations (id, org_id, workspace_id, user_id, title_ct) values (%s, %s, %s, %s, %s)"
            " returning id",
            [
                conv_id,
                m.org_id,
                m.workspace_id,
                p.user_id,
                self.keys.seal(
                    scope,
                    Field.workspace("conversation.title", m.org_id, m.workspace_id, conv_id),
                    title,
                ),
            ],
        ).fetchone()
        if conv is None:
            raise NotFound("Chat not found.")
        conv = {"id": conv["id"], "title": title}
        lmqa_audit.append(
            scope,
            org_id=m.org_id,
            workspace_id=m.workspace_id,
            actor_id=p.user_id,
            action="conversation.created",
            target_type="conversation",
            target_id=conv["id"],
        )
        return conv

    # ------------------------------------------------------------------ re-open
    def with_current_citations(
        self, scope: Scope, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Stored answers with citation text re-read under RLS now: a revoked or changed source shows unavailable.
        `rows` are queries rows selected with QUERY_COLUMNS (sealed)."""
        rows = [open_query(self.keys, scope, r) for r in rows]
        results = [dict(r["result"]) for r in rows]
        ids = [c["chunk_id"] for res in results for c in res.get("citations", [])]
        current = self._retrieval.current_chunks(scope, ids)
        out = []
        for r, res in zip(rows, results, strict=True):
            for c in res.get("citations", []):
                chunk = current.get(c["chunk_id"])
                if chunk is None or chunk[1] != c.get("chunk_sha256"):
                    c["text"], c["unavailable"] = None, True
                else:
                    c["text"] = chunk[0]
            res.update(
                {
                    "id": str(r["id"]),
                    "question": r["question"],
                    "created_at": r["created_at"].isoformat(),
                    "conversation_id": str(r["conversation_id"]) if r["conversation_id"] else None,
                }
            )
            res.setdefault("standalone_question", r.get("standalone_question") or r["question"])
            out.append(res)
        return out

    def get(self, p: Principal, query_id: str) -> dict[str, Any] | None:
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(
                f"select {QUERY_COLUMNS} from queries where id = %s",  # noqa: S608 - constant
                [query_id],
            ).fetchone()
            return None if row is None else self.with_current_citations(scope, [row])[0]
