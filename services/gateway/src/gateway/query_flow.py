"""Gated query release (blueprint 11.6).

  retrieval (RLS, ledger aliases) -> generation draft -> citation validator (deterministic V1-V8)
  -> entailment (can only remove) -> V3 re-read of chunk hashes under RLS
  -> ONE transaction: query row + retrieval ledger + audit event -> commit -> only then release.

A sentence that fails any check never reaches the client; the client sees a visible "could not be
verified" marker. If any step fails, nothing is released (fail closed).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from psycopg.types.json import Jsonb

import lmqa_audit
from citation_validator import apply_entailment, build_result, entailment_claims, recheck_integrity, validate
from generation import GenerationService, LLMError
from lmqa_db import Database
from lmqa_models.errors import BadRequest, Unavailable
from lmqa_models.principal import Principal
from lmqa_models.rag import Dropped, Source
from lmqa_models.settings import Settings
from retrieval import EmbeddingError, RetrievalService

RETRIEVAL_HEADROOM_TOKENS = 1500


class QueryFlow:
    def __init__(
        self, settings: Settings, db: Database, retrieval: RetrievalService, generation: GenerationService
    ) -> None:
        self._s = settings
        self._db = db
        self._retrieval = retrieval
        self._generation = generation

    def ask(self, p: Principal, question: str) -> dict[str, Any]:
        started = time.monotonic()
        q = " ".join(question.split())
        if not 3 <= len(q) <= 2000:
            raise BadRequest("Ask a question between 3 and 2,000 characters.")
        try:
            sources, dropped = self._retrieval.retrieve(
                p, q, budget_tokens=self._s.context_budget_tokens - RETRIEVAL_HEADROOM_TOKENS
            )
        except EmbeddingError as exc:
            raise Unavailable(f"No answer was released: {exc}") from exc

        ledger: dict[str, Source] = {}
        answerable, verdicts = False, []
        tokens_in = tokens_out = 0
        model, prompt_sha = self._generation.client.model, None
        if sources:
            try:
                draft = self._generation.draft(q, sources)
                ledger = {s.alias: s for s in draft.sources}
                dropped += [Dropped(cid, "token_budget", 0.0) for cid in draft.dropped_for_budget]
                tokens_in, tokens_out, model, prompt_sha = (
                    draft.tokens_in,
                    draft.tokens_out,
                    draft.model,
                    draft.prompt_sha256,
                )
                answerable, verdicts = validate(draft.data, ledger)
                if self._s.verify_entailment:
                    check = self._generation.entailment(entailment_claims(verdicts), ledger)
                    apply_entailment(verdicts, check.verdicts)
                    tokens_in, tokens_out = tokens_in + check.tokens_in, tokens_out + check.tokens_out
            except LLMError as exc:
                raise Unavailable(f"No answer was released: {exc}") from exc
        return self._release(
            p, q, ledger, dropped, answerable, verdicts, model, prompt_sha, tokens_in, tokens_out, started
        )

    def _release(
        self,
        p: Principal,
        question: str,
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
            row = scope.execute(
                "insert into queries (org_id, workspace_id, user_id, question, outcome, result, model,"
                " prompt_sha256, tokens_in, tokens_out, latency_ms)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id, created_at",
                [
                    m.org_id,
                    m.workspace_id,
                    p.user_id,
                    question,
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
            released = "\n".join(s.get("text", "") for s in result["segments"])
            lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="query.answered",
                target_type="query",
                target_id=query_id,
                payload={
                    "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
                    "released_sha256": hashlib.sha256(released.encode()).hexdigest(),
                    "outcome": result["outcome"],
                    "verified": result["stats"]["verified"],
                    "removed": result["stats"]["removed"],
                    "chunks": [s.chunk_id for s in ledger.values()],
                    "dropped": [{"chunk_id": d.chunk_id, "reason": d.reason} for d in dropped[:20]],
                    "prompt_sha256": prompt_sha,
                    "model": model,
                },
            )
        # Committed: query, ledger and audit event. Only now is anything released.
        texts = {s.chunk_id: s.text for s in ledger.values()}
        for c in result["citations"]:
            c["text"] = texts[c["chunk_id"]]
        result.update({"id": query_id, "question": question, "created_at": row["created_at"].isoformat()})
        return result

    def history(self, p: Principal, limit: int = 30) -> list[dict[str, Any]]:
        with self._db.scoped(p.user_id) as scope:
            rows = scope.execute(
                "select id, question, outcome, created_at, result->'stats' as stats from queries"
                " order by created_at desc limit %s",
                [limit],
            ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "question": r["question"],
                "outcome": r["outcome"],
                "created_at": r["created_at"].isoformat(),
                "stats": r["stats"],
            }
            for r in rows
        ]

    def get(self, p: Principal, query_id: str) -> dict[str, Any] | None:
        """Re-open a past answer. Citation text is re-read under RLS, so a revoked source stays hidden."""
        with self._db.scoped(p.user_id) as scope:
            row = scope.execute(
                "select id, question, result, created_at from queries where id = %s", [query_id]
            ).fetchone()
            if row is None:
                return None
            result = dict(row["result"])
            current = self._retrieval.current_chunks(scope, [c["chunk_id"] for c in result.get("citations", [])])
        for c in result.get("citations", []):
            chunk = current.get(c["chunk_id"])
            if chunk is None or chunk[1] != c.get("chunk_sha256"):
                c["text"], c["unavailable"] = None, True
            else:
                c["text"] = chunk[0]
        result.update({"id": str(row["id"]), "question": row["question"], "created_at": row["created_at"].isoformat()})
        return result
