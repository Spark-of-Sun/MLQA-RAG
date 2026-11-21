"""Conversational, gated query release (blueprint 11.3 to 11.6).

  load the conversation (RLS: only the author can see it) -> condense the follow-up into a standalone question
  -> retrieval (RLS, aliases; the previous turn's cited passages stay available) -> generation draft (earlier
  turns are context only, never a source) -> citation validator (deterministic V1-V8) -> entailment (can only
  remove) -> V3 re-read of chunk hashes under RLS
  -> ONE transaction: chat (created on its first question) + query row + retrieval ledger + audit event
  -> commit -> only then release.

A sentence that fails any check never reaches the client; the client sees a visible "could not be verified"
marker. If any step fails, nothing is released and no chat is created (fail closed).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

import lmqa_audit
from citation_validator import apply_entailment, build_result, entailment_claims, recheck_integrity, validate
from generation import GenerationService, LLMError, Turn
from lmqa_db import Database, Scope
from lmqa_models.errors import BadRequest, NotFound, Unavailable
from lmqa_models.principal import Principal
from lmqa_models.rag import Dropped, Source
from lmqa_models.settings import Settings
from retrieval import EmbeddingError, RetrievalService

RETRIEVAL_HEADROOM_TOKENS = 1500
HISTORY_TURNS = 4


def released_text(result: dict[str, Any]) -> str:
    """What the user actually saw: verified sentences and the refusal, never removed claims."""
    return " ".join(s["text"] for s in result.get("segments", []) if s.get("type") in {"sentence", "refusal"})


def chat_title(question: str) -> str:
    q = " ".join(question.split())
    if len(q) <= 60:
        return q
    cut = q.rfind(" ", 0, 60)
    return q[: cut if cut > 30 else 60].rstrip(" ,;:") + "…"


class QueryFlow:
    def __init__(
        self, settings: Settings, db: Database, retrieval: RetrievalService, generation: GenerationService
    ) -> None:
        self._s = settings
        self._db = db
        self._retrieval = retrieval
        self._generation = generation

    # ------------------------------------------------------------------ ask
    def ask(self, p: Principal, question: str, conversation_id: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        q = " ".join(question.split())
        if not 3 <= len(q) <= 2000:
            raise BadRequest("Ask a question between 3 and 2,000 characters.")

        history: list[Turn] = []
        carry: list[str] = []
        if conversation_id:
            with self._db.scoped(p.user_id) as scope:
                if scope.execute("select 1 from conversations where id = %s", [conversation_id]).fetchone() is None:
                    raise NotFound("Chat not found.")
                rows = scope.execute(
                    "select question, result from queries where conversation_id = %s order by created_at desc limit %s",
                    [conversation_id, HISTORY_TURNS],
                ).fetchall()
            rows.reverse()
            history = [Turn(r["question"], released_text(r["result"])) for r in rows]
            if rows:
                carry = [c["chunk_id"] for c in rows[-1]["result"].get("citations", [])]

        tokens_in = tokens_out = 0
        standalone = q
        try:
            if history:
                condensed = self._generation.condense(history, q)
                standalone, tokens_in, tokens_out = condensed.question, condensed.tokens_in, condensed.tokens_out
            sources, dropped = self._retrieval.retrieve(
                p,
                standalone,
                budget_tokens=self._s.context_budget_tokens - RETRIEVAL_HEADROOM_TOKENS,
                carry_chunk_ids=carry,
            )
        except EmbeddingError as exc:
            raise Unavailable(f"No answer was released: {exc}") from exc

        ledger: dict[str, Source] = {}
        answerable, verdicts = False, []
        model, prompt_sha = self._generation.client.model, None
        if sources:
            try:
                draft = self._generation.draft(q, sources, history=history, standalone=standalone)
                ledger = {s.alias: s for s in draft.sources}
                dropped += [Dropped(cid, "token_budget", 0.0) for cid in draft.dropped_for_budget]
                tokens_in, tokens_out = tokens_in + draft.tokens_in, tokens_out + draft.tokens_out
                model, prompt_sha = draft.model, draft.prompt_sha256
                answerable, verdicts = validate(draft.data, ledger, entailment=self._s.verify_entailment)
                if self._s.verify_entailment:
                    check = self._generation.entailment(entailment_claims(verdicts), ledger)
                    apply_entailment(verdicts, check.verdicts)
                    tokens_in, tokens_out = tokens_in + check.tokens_in, tokens_out + check.tokens_out
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
            )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise NotFound("This chat was deleted while the answer was being prepared.") from exc

    def _release(
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
                }
            )
            result["standalone_question"] = standalone
            if conversation_id is None:
                conv = scope.execute(
                    "insert into conversations (org_id, workspace_id, user_id, title) values (%s, %s, %s, %s)"
                    " returning id, title",
                    [m.org_id, m.workspace_id, p.user_id, chat_title(question)],
                ).fetchone()
                if conv is not None:
                    lmqa_audit.append(
                        scope,
                        org_id=m.org_id,
                        workspace_id=m.workspace_id,
                        actor_id=p.user_id,
                        action="conversation.created",
                        target_type="conversation",
                        target_id=conv["id"],
                    )
            else:
                conv = scope.execute(
                    "update conversations set updated_at = now() where id = %s returning id, title", [conversation_id]
                ).fetchone()
            if conv is None:
                raise NotFound("Chat not found.")
            row = scope.execute(
                "insert into queries (org_id, workspace_id, user_id, conversation_id, question, standalone_question,"
                " outcome, result, model, prompt_sha256, tokens_in, tokens_out, latency_ms)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id, created_at",
                [
                    m.org_id,
                    m.workspace_id,
                    p.user_id,
                    conv["id"],
                    question,
                    standalone,
                    result["outcome"],
                    Jsonb(result),
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
                    "conversation_id": str(conv["id"]),
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "released_sha256": hashlib.sha256(released_text(result).encode()).hexdigest(),
                    "outcome": result["outcome"],
                    "verified": result["stats"]["verified"],
                    "removed": result["stats"]["removed"],
                    "chunks": [s.chunk_id for s in ledger.values()],
                    "dropped": [{"chunk_id": d.chunk_id, "reason": d.reason} for d in dropped[:20]],
                    "prompt_sha256": prompt_sha,
                    "model": model,
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
                "conversation_id": str(conv["id"]),
                "conversation_title": conv["title"],
            }
        )
        return result

    # ------------------------------------------------------------------ re-open
    def with_current_citations(self, scope: Scope, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stored answers with citation text re-read under RLS now: a revoked or changed source shows unavailable."""
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
                    "conversation_id": str(r["conversation_id"]),
                }
            )
            res.setdefault("standalone_question", r.get("standalone_question") or r["question"])
            out.append(res)
        return out

    def get(self, p: Principal, query_id: str) -> dict[str, Any] | None:
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(
                "select id, conversation_id, question, standalone_question, result, created_at from queries"
                " where id = %s",
                [query_id],
            ).fetchone()
            return None if row is None else self.with_current_citations(scope, [row])[0]
