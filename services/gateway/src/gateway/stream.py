"""Sentence-gated SSE delivery (blueprint 4.4, 11.6, 17.3, D15, G7.7 to G7.12, G8.4).

    POST /v1/queries/stream    ->  text/event-stream

Events (each with `id: <seq>` so `Last-Event-ID` resumes):
    meta      {query_id, request_id}                    first, before any model call
    sentence  {seq, text, citations[]}                  a verified sentence, after its audit event committed
    stripped  {seq}                                     a sentence that failed validation (marker only, no text)
    done      {outcome, citations[], model, latency_ms} final citation list
    error     {detail}                                  the stream stopped; nothing after this was released

Write-ahead rule: `query.started` commits before retrieval; each `segment.released` commits (with the
query_segments row) before its sentence is sent; if any audit write fails the stream emits `error` and stops
(G7.9). The gateway releases a sentence only with a verdict signed by the validator for this request and this
exact text (verify_verdict); the final `query.completed` stores the SHA-256 of everything released and the verdict
tokens, so "released equals validated" is checkable later.

Revocation: the stream registers a cancel callback with the principal cache; a revocation message cuts the stream
within the SLO and the provider connection is closed (G3.4, G6.10).
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import lmqa_audit
from citation_validator.streaming import StreamValidator, verify_verdict
from generation.streaming import StreamError, StreamState, budget_prompt, stream_answer
from lmqa_auth.context import ContextTokenError, Signer
from lmqa_db import Database
from lmqa_keys import Field, FieldCipher
from lmqa_models.contracts import feature_enabled
from lmqa_models.errors import BadRequest
from lmqa_models.principal import Principal
from lmqa_models.settings import Settings

log = logging.getLogger("gateway.stream")
HEARTBEAT_SECONDS = 15.0


def sse(event: str, data: dict[str, Any], event_id: int | None = None) -> bytes:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":"), default=str))
    return ("\n".join(lines) + "\n\n").encode()


@dataclass
class StreamDeps:
    settings: Settings
    db: Database
    retrieval: Any  # retrieval.RetrievalService
    validator_signer: Signer
    trust_roots: dict[str, Any]  # root kid -> public key, for verdict verification
    register_stream: Callable[[str, Callable[[], None]], Callable[[], None]]
    keys: FieldCipher  # questions, results, segment text and chat titles are sealed (R-51.3)
    nli: Callable[[str, list[str]], tuple[bool, float]] | None = None


class SentenceStream:
    def __init__(self, deps: StreamDeps) -> None:
        self._d = deps

    def run(  # noqa: C901, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        question: str,
        *,
        last_event_id: int | None = None,
        query_id: str | None = None,
    ) -> Iterator[bytes]:
        if last_event_id is not None and query_id:
            yield from self._resume(p, query_id, last_event_id)
            return
        q = " ".join(question.split())
        if not 3 <= len(q) <= 2000:
            raise BadRequest("Ask a question between 3 and 2,000 characters.")
        m = p.membership
        assert m is not None and m.workspace_id
        request_id = str(uuid.uuid4())
        state = StreamState()
        unregister = self._d.register_stream(p.user_id, state.cancel.set)
        started = time.monotonic()
        released: list[str] = []
        verdict_tokens: list[str] = []
        try:
            # 1. write-ahead: the query row and query.started commit before anything else happens
            keys = self._d.keys
            with self._d.db.scoped(p.user_id) as scope:
                # A chat row only while the frozen `chats` feature is on (DEV-21); otherwise conversation_id is null.
                conv_id = str(uuid.uuid4()) if feature_enabled("chats") else None
                if conv_id:
                    scope.execute(
                        "insert into conversations (id, org_id, workspace_id, user_id, title_ct)"
                        " values (%s, %s, %s, %s, %s)",
                        [
                            conv_id,
                            m.org_id,
                            m.workspace_id,
                            p.user_id,
                            keys.seal(
                                scope,
                                Field.workspace(
                                    "conversation.title", m.org_id, m.workspace_id, conv_id
                                ),
                                q[:80],
                            ),
                        ],
                    )
                qid = str(uuid.uuid7())
                scope.execute(
                    "insert into queries (id, org_id, workspace_id, user_id, question_ct, outcome, result_ct,"
                    " conversation_id, request_id, delivery, state) values (%s, %s, %s, %s, %s, 'refused', %s,"
                    " %s, %s, 'sentence', 'streaming')",
                    [
                        qid,
                        m.org_id,
                        m.workspace_id,
                        p.user_id,
                        keys.seal(scope, self._field("query.question", m, qid), q),
                        keys.seal_json(scope, self._field("query.result", m, qid), {}),
                        conv_id,
                        request_id,
                    ],
                )
                lmqa_audit.append(
                    scope,
                    org_id=m.org_id,
                    workspace_id=m.workspace_id,
                    actor_id=p.user_id,
                    action="query.started",
                    target_type="query",
                    target_id=qid,
                    payload={"request_id": request_id, "delivery": "sentence"},
                )
            yield sse("meta", {"query_id": qid, "request_id": request_id})

            # 2. retrieval under RLS, ledger written by retrieval
            found = self._d.retrieval.retrieve(
                p, q, alternatives=[], budget_tokens=self._d.settings.context_budget_tokens
            )
            sources = found.sources
            with self._d.db.scoped(p.user_id) as scope:
                self._d.retrieval.record_ledger(scope, qid, sources)
            if not sources:
                yield from self._finish(
                    p, qid, request_id, "refused", released, verdict_tokens, state, started, []
                )
                return

            # 3. budgeted prompt and the validator for this request
            prompt = budget_prompt(self._d.settings, q, sources)
            ledger = {s.alias: s for s in prompt.kept}

            def current_hashes(chunk_ids: list[str]) -> dict[str, str]:
                with self._d.db.scoped(p.user_id) as scope:
                    rows = scope.execute(
                        "select id, text_sha256 from chunks where id = any(%s::uuid[])", [chunk_ids]
                    ).fetchall()
                return {str(r["id"]): str(r["text_sha256"]) for r in rows}

            validator = StreamValidator(
                request_id, ledger, current_hashes, self._d.validator_signer, entail=self._d.nli
            )
            citations: dict[str, dict[str, Any]] = {}
            seq = 0
            deltas = self._pump(stream_answer(self._d.settings, prompt, state), state)
            for item in deltas:
                if item is None:
                    yield b": keep-alive\n\n"
                    continue
                for verdict in validator.feed(item):
                    seq += 1
                    yield from self._release(
                        p,
                        qid,
                        request_id,
                        seq,
                        verdict,
                        released,
                        verdict_tokens,
                        citations,
                        ledger,
                    )
            for verdict in validator.finish():
                seq += 1
                yield from self._release(
                    p, qid, request_id, seq, verdict, released, verdict_tokens, citations, ledger
                )
            outcome = "answered" if released else "refused"
            yield from self._finish(
                p,
                qid,
                request_id,
                outcome,
                released,
                verdict_tokens,
                state,
                started,
                list(citations.values()),
            )
        except (StreamError, ContextTokenError) as exc:
            log.warning("stream stopped: %s", type(exc).__name__)
            yield sse("error", {"detail": "No further text was released."})
        except Exception:
            log.exception("stream failed")
            yield sse("error", {"detail": "No further text was released."})
            raise
        finally:
            state.cancel.set()
            unregister()

    @staticmethod
    def _field(purpose: str, m: Any, object_id: str) -> Field:
        return Field.workspace(purpose, m.org_id, m.workspace_id, object_id)

    @staticmethod
    def _pump(source: Iterator[str], state: StreamState) -> Iterator[str | None]:  # noqa: C901 - one linear flow; splitting it is a DEV-33 follow-up
        """Run the provider stream in a thread so heartbeats and cancellation do not wait for the model."""
        q: queue.Queue[tuple[str, Any]] = queue.Queue(
            maxsize=256
        )  # bounded: backpressure on the provider

        def work() -> None:
            try:
                for delta in source:
                    if state.cancel.is_set():
                        break
                    q.put(("delta", delta))
                q.put(("end", None))
            except Exception as exc:
                q.put(("error", exc))

        threading.Thread(target=work, name="generation-stream", daemon=True).start()
        while True:
            try:
                kind, value = q.get(timeout=HEARTBEAT_SECONDS)
            except queue.Empty:
                if state.cancel.is_set():
                    raise StreamError("cancelled") from None
                yield None
                continue
            if kind == "end":
                return
            if kind == "error":
                raise StreamError("generation failed") from value
            if state.cancel.is_set():
                raise StreamError("cancelled")
            yield value

    def _release(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        qid: str,
        request_id: str,
        seq: int,
        verdict: Any,
        released: list[str],
        tokens: list[str],
        citations: dict[str, dict[str, Any]],
        ledger: dict[str, Any],
    ) -> Iterator[bytes]:
        m = p.membership
        assert m is not None
        if verdict.ok:
            verify_verdict(
                verdict.token, request_id=request_id, text=verdict.text, roots=self._d.trust_roots
            )
        kind = (
            "refusal"
            if verdict.refusal and verdict.ok
            else ("sentence" if verdict.ok else "stripped")
        )
        with self._d.db.scoped(p.user_id) as scope:
            event_id = lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="segment.released",
                target_type="query",
                target_id=qid,
                payload={
                    "seq": seq,
                    "kind": kind,
                    "sha256": verdict.sha256,
                    "request_id": request_id,
                },
            )
            scope.execute(
                "insert into query_segments (query_id, seq, org_id, workspace_id, user_id, kind, text_ct,"
                " text_sha256, verdict, citations, audit_event_id)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                [
                    qid,
                    seq,
                    m.org_id,
                    m.workspace_id,
                    p.user_id,
                    kind,
                    self._d.keys.seal(
                        scope, self._field("segment.text", m, f"{qid}:{seq}"), verdict.text
                    )
                    if verdict.ok
                    else None,
                    verdict.sha256,
                    verdict.token,
                    json.dumps(verdict.citations),
                    event_id,
                ],
            )
        tokens.append(verdict.token)
        if not verdict.ok:
            yield sse("stripped", {"seq": seq}, seq)
            return
        released.append(verdict.text)
        cites = []
        for c in verdict.citations:
            src = ledger[c["alias"]]
            entry = citations.setdefault(
                c["chunk_id"],
                {
                    "number": len(citations) + 1,
                    "chunk_id": c["chunk_id"],
                    "document_id": src.document_id,
                    "document_title": src.document_title,
                    "section": src.section,
                    "pages": src.pages(),
                },
            )
            cites.append(
                {"number": entry["number"], "chunk_id": c["chunk_id"], "spans": c["spans"]}
            )
        yield sse(
            "sentence",
            {"seq": seq, "text": verdict.text, "citations": cites, "refusal": kind == "refusal"},
            seq,
        )

    def _finish(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        p: Principal,
        qid: str,
        request_id: str,
        outcome: str,
        released: list[str],
        tokens: list[str],
        state: StreamState,
        started: float,
        citations: list[dict[str, Any]],
    ) -> Iterator[bytes]:
        m = p.membership
        assert m is not None
        digest = hashlib.sha256("\n".join(released).encode()).hexdigest()
        latency = int((time.monotonic() - started) * 1000)
        result = {
            "outcome": outcome,
            "sentences": released,
            "citations": citations,
            "delivery": "sentence",
        }
        with self._d.db.scoped(p.user_id) as scope:
            scope.execute(
                "update queries set state = 'completed', outcome = %s, result_ct = %s, released_sha256 = %s,"
                " model = %s, tokens_in = %s, tokens_out = %s, latency_ms = %s where id = %s",
                [
                    outcome,
                    self._d.keys.seal_json(scope, self._field("query.result", m, qid), result),
                    digest,
                    state.model or None,
                    state.tokens_in,
                    state.tokens_out,
                    latency,
                    qid,
                ],
            )
            lmqa_audit.append(
                scope,
                org_id=m.org_id,
                workspace_id=m.workspace_id,
                actor_id=p.user_id,
                action="query.completed",
                target_type="query",
                target_id=qid,
                payload={
                    "request_id": request_id,
                    "outcome": outcome,
                    "released_sha256": digest,
                    "verdicts": [hashlib.sha256(t.encode()).hexdigest() for t in tokens],
                    "model": state.model,
                },
            )
        yield sse(
            "done",
            {
                "outcome": outcome,
                "citations": citations,
                "model": state.model,
                "latency_ms": latency,
            },
        )

    def _resume(self, p: Principal, query_id: str, after: int) -> Iterator[bytes]:
        """Replay only released and audited segments after `after` (G7.11)."""
        with self._d.db.scoped(p.user_id) as scope:
            keys = self._d.keys
            rows = [
                {
                    **r,
                    "text": keys.open(
                        scope,
                        Field.workspace(
                            "segment.text", r["org_id"], r["workspace_id"], f"{query_id}:{r['seq']}"
                        ),
                        r["text_ct"],
                    ),
                }
                for r in scope.execute(
                    "select seq, kind, text_ct, citations, org_id, workspace_id from query_segments"
                    " where query_id = %s and seq > %s order by seq",
                    [query_id, after],
                ).fetchall()
            ]
            q = scope.execute(
                "select id, org_id, workspace_id, state, outcome, result_ct from queries where id = %s",
                [query_id],
            ).fetchone()
            if q is not None:
                q = {
                    **q,
                    "result": keys.open_json(
                        scope,
                        Field.workspace("query.result", q["org_id"], q["workspace_id"], q["id"]),
                        q["result_ct"],
                    ),
                }
        for r in rows:
            if r["kind"] == "stripped":
                yield sse("stripped", {"seq": r["seq"]}, r["seq"])
            else:
                yield sse(
                    "sentence",
                    {
                        "seq": r["seq"],
                        "text": r["text"],
                        "citations": r["citations"],
                        "refusal": r["kind"] == "refusal",
                    },
                    r["seq"],
                )
        if q and q["state"] == "completed":
            yield sse(
                "done",
                {"outcome": q["outcome"], "citations": (q["result"] or {}).get("citations", [])},
            )
