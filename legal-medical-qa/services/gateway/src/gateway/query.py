"""The gated query flow (doc 4.4, 11.6): nothing unverified is ever released.

Order for one request: write-ahead ``query.started`` -> retrieval (a ledger row, counts only) ->
generation streams UNVERIFIED text -> the text is forwarded to the validator over a WebSocket ->
for every sentence the validator returns a signed verdict. The Gateway releases a sentence only if
it holds a verdict that

* carries a valid signature from a certified validator key,
* is for THIS request and the next expected sentence index,
* is for exactly the sentence text it is about to send (hash compared), and
* passed.

A ``segment.released`` audit event (hashes only) is committed BEFORE each sentence is sent; if any
audit write fails, the stream stops. A revocation message or a principal-version change cuts the
stream. Sentences the validator rejects are replaced by a visible notice ("could not be verified
and was removed") with a reason code; if nothing at all verifies, the answer is the canonical
refusal, sent as a system notice and not as model text.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import httpx
import websockets

from gateway.principal import Principal, PrincipalResolver
from gateway.resume import ResumeBuffer
from lmqa_audit import AuditEvent, AuditWriter
from lmqa_auth import ContextClaims, ContextSigner, ContextTokenError, ContextVerifier
from lmqa_db import Database, DbContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


LOG = logging.getLogger("gateway.query")
CANONICAL_REFUSAL: Final = "The provided documents do not address this."
STRIP_NOTICE: Final = "A claim in this answer could not be verified and was removed."
VERDICT_PREFIX: Final = b"lmqa/verdict/v1|"
MAX_REGENERATIONS: Final = 2
HTTP_FORBIDDEN: Final = 403
HTTP_UNAVAILABLE: Final = 503


def signing_bytes(payload: dict[str, Any]) -> bytes:
    """The bytes the validator signed (must equal the validator's own definition; tested)."""
    return VERDICT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sse(event: str, data: dict[str, Any], event_id: str | None = None) -> bytes:
    """One server-sent event frame."""
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class StreamStopped(Exception):  # noqa: N818 - control flow for a deliberate, audited stop
    """The stream must end now (integrity failure, audit failure or revocation)."""

    def __init__(self, code: str) -> None:
        """``code`` is the stable reason shown to the client."""
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class QueryDeps:
    """Everything the flow needs; all real."""

    signer: ContextSigner
    verifier: ContextVerifier
    db: Database
    audit: AuditWriter
    http: httpx.AsyncClient
    resolver: PrincipalResolver
    resume: ResumeBuffer
    retrieval_url: str
    generation_url: str
    validator_http_url: str
    validator_ws_url: str


@dataclass(slots=True)
class _Run:
    deps: QueryDeps
    principal: Principal
    ctx: DbContext
    request_id: UUID
    cut: asyncio.Event
    next_index: int = 0
    event_no: int = 0
    released: list[str] = field(default_factory=list[str])
    verdicts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    citations: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    passed_content: int = 0
    failed_content: int = 0
    meta: dict[str, Any] = field(default_factory=dict[str, Any])

    async def token(self, audience: str) -> str:
        p = self.principal
        claims = ContextClaims(
            p.user_id,
            p.org_id,
            p.workspace_id,
            p.role,
            "verified",
            p.scope_hash,
            p.scope_version,
            p.principal_version,
            self.request_id,
            "",
            "",
            0,
        )
        return await self.deps.signer.mint(audience=audience, claims=claims)

    async def audit(self, event: AuditEvent) -> None:
        """Write an audit event; any failure stops the stream (principle 10)."""
        try:
            async with self.deps.db.scoped(self.ctx) as s:
                await self.deps.audit.append(s, self.ctx.org, self.ctx.workspace_id, event)
        except Exception as exc:
            LOG.exception("audit write failed; stopping the stream")
            msg = "audit_unavailable"
            raise StreamStopped(msg) from exc

    def check_alive(self) -> None:
        if self.cut.is_set():
            msg = "revoked"
            raise StreamStopped(msg)

    async def emit(self, event: str, data: dict[str, Any]) -> bytes:
        """Frame an event, remember it for resume, and return the bytes to send."""
        self.event_no += 1
        frame = sse(event, data, f"{self.request_id}:{self.event_no}")
        await self.deps.resume.append(self.request_id, self.principal.user_id, self.event_no, frame)
        return frame


async def _verify(run: _Run, verdict: dict[str, Any]) -> dict[str, Any]:
    payload = verdict["payload"]
    try:
        await run.deps.verifier.verify_signature(
            verdict["certificate"], signing_bytes(payload), base64.b64decode(verdict["signature"])
        )
    except ContextTokenError as exc:
        msg = "verdict_signature_invalid"
        raise StreamStopped(msg) from exc
    if payload["request_id"] != str(run.request_id):
        msg = "verdict_for_another_request"
        raise StreamStopped(msg)
    if payload["index"] != run.next_index:
        msg = "verdict_out_of_order"
        raise StreamStopped(msg)
    if hashlib.sha256(payload["sentence"].encode()).hexdigest() != payload["sentence_sha256"]:
        msg = "verdict_hash_mismatch"
        raise StreamStopped(msg)
    run.next_index += 1
    return payload  # type: ignore[no-any-return]


async def _release(run: _Run, payload: dict[str, Any]) -> AsyncIterator[bytes]:
    """Release (or strip) one verified verdict, with the write-ahead audit record first."""
    run.verdicts.append(
        {
            k: payload[k]
            for k in ("index", "sentence_sha256", "passed", "failed_check", "checks", "aliases")
        }
    )
    if not payload["passed"]:
        run.failed_content += 1
        await run.audit(
            AuditEvent(
                "segment.stripped",
                "ok",
                "workspace",
                run.principal.user_id,
                run.principal.role,
                f"sha256:{payload['sentence_sha256']}",
                payload["failed_check"],
                run.request_id,
            )
        )
        yield await run.emit(
            "notice", {"text": STRIP_NOTICE, "reason": payload["failed_check"], "kind": "stripped"}
        )
        return
    await run.audit(
        AuditEvent(
            "segment.released",
            "ok",
            "workspace",
            run.principal.user_id,
            run.principal.role,
            f"sha256:{payload['sentence_sha256']}",
            None,
            run.request_id,
        )
    )  # BEFORE the send
    if not payload["refusal"] and payload["aliases"]:
        run.passed_content += 1
    run.released.append(payload["sentence"])
    run.citations.extend(payload["citations"])
    yield await run.emit(
        "sentence",
        {
            "text": payload["sentence"],
            "aliases": payload["aliases"],
            "citations": payload["citations"],
            "index": payload["index"],
        },
    )


async def _generation_deltas(run: _Run, question: str, *, use_cache: bool) -> AsyncIterator[str]:
    token = await run.token("generation")
    async with run.deps.http.stream(
        "POST",
        f"{run.deps.generation_url}/internal/v1/answer",
        json={"question": question, "use_cache": use_cache},
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        if response.status_code != 200:  # noqa: PLR2004
            msg = "generation_unavailable"
            raise StreamStopped(msg)
        event = ""
        async for line in response.aiter_lines():
            run.check_alive()
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event == "meta":
                    run.meta = data
                elif event == "delta":
                    yield str(data["text"])


async def _gated_stream(
    run: _Run, question: str, *, use_cache: bool = True
) -> AsyncIterator[bytes]:
    """Sentence-gated delivery: verdicts are consumed while generation is still streaming."""
    token = await run.token("citation_validator")
    async with websockets.connect(
        run.deps.validator_ws_url, additional_headers={"Authorization": f"Bearer {token}"}
    ) as ws:

        async def feed() -> None:
            async for delta in _generation_deltas(run, question, use_cache=use_cache):
                await ws.send(json.dumps({"delta": delta}))
            await ws.send(json.dumps({"end": True}))

        feeder = asyncio.create_task(feed())
        try:
            async for raw in ws:
                run.check_alive()
                frame = json.loads(raw)
                if "verdict" in frame:
                    payload = await _verify(run, frame["verdict"])
                    async for chunk in _release(run, payload):
                        yield chunk
            await feeder
        finally:
            if not feeder.done():
                feeder.cancel()


async def _buffered_attempt(run: _Run, question: str, *, use_cache: bool) -> list[dict[str, Any]]:
    text_parts = [d async for d in _generation_deltas(run, question, use_cache=use_cache)]
    token = await run.token("citation_validator")
    response = await run.deps.http.post(
        f"{run.deps.validator_http_url}/internal/v1/validate-answer",
        json={"answer": "".join(text_parts)},
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:  # noqa: PLR2004
        msg = "validator_unavailable"
        raise StreamStopped(msg)
    return list(response.json()["verdicts"])


async def run_query(  # noqa: C901, PLR0912 - one gated flow whose order is the safety property
    deps: QueryDeps,
    principal: Principal,
    ctx: DbContext,
    question: str,
    request_id: UUID | None = None,
) -> AsyncIterator[bytes]:
    """The whole gated flow as SSE bytes. Never raises: failures become an ``error`` event."""
    run = _Run(deps, principal, ctx, request_id or uuid.uuid4(), asyncio.Event())
    deps.resolver.streams.setdefault(principal.user_id, set()).add(run.cut)
    qhash = hashlib.sha256(question.encode()).hexdigest()
    try:
        await run.audit(
            AuditEvent(
                "query.started",
                "ok",
                "workspace",
                principal.user_id,
                principal.role,
                f"sha256:{qhash}",
                None,
                run.request_id,
            )
        )
        yield await run.emit("status", {"stage": "retrieving", "request_id": str(run.request_id)})
        token = await run.token("retrieval")
        found = await deps.http.post(
            f"{deps.retrieval_url}/internal/v1/search",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
        )
        refusal = {HTTP_FORBIDDEN: "forbidden", HTTP_UNAVAILABLE: "retrieval_unavailable"}.get(
            found.status_code
        )
        if refusal is not None:
            yield sse("error", {"code": refusal})
            return
        found.raise_for_status()
        yield await run.emit("status", {"stage": "generating", "kept": found.json()["kept"]})
        yield await run.emit("status", {"stage": "validating"})
        buffered = principal.delivery_mode == "buffered"
        attempts = 1 + (MAX_REGENERATIONS if principal.on_fail == "regenerate" else 0)
        if not buffered:
            async for chunk in _gated_stream(run, question):
                yield chunk
        else:
            for attempt in range(attempts):
                verdicts = await _buffered_attempt(run, question, use_cache=attempt == 0)
                run.next_index = 0
                if (
                    all(v["payload"]["passed"] for v in verdicts)
                    or attempt == attempts - 1
                    or principal.on_fail != "regenerate"
                ):
                    for item in verdicts:
                        async for chunk in _release(run, await _verify(run, item)):
                            yield chunk
                    break
        if principal.on_fail == "refuse" and run.failed_content:
            run.released.clear()
            run.passed_content = 0
        if run.passed_content == 0 and not any(s == CANONICAL_REFUSAL for s in run.released):
            await run.audit(
                AuditEvent(
                    "answer.refused",
                    "ok",
                    "workspace",
                    principal.user_id,
                    principal.role,
                    None,
                    "no_verified_answer",
                    run.request_id,
                )
            )
            yield await run.emit(
                "notice",
                {"text": CANONICAL_REFUSAL, "reason": "no_verified_answer", "kind": "refusal"},
            )
        yield await run.emit("citations", {"citations": run.citations})
        await run.audit(
            AuditEvent(
                "query.completed",
                "ok",
                "workspace",
                principal.user_id,
                principal.role,
                f"sha256:{qhash}",
                None,
                run.request_id,
                payload={
                    "question": question,
                    "answer": " ".join(run.released),
                    "verdicts": run.verdicts,
                    "meta": run.meta,
                },
            )
        )
        yield await run.emit("done", {"request_id": str(run.request_id)})
    except StreamStopped as stop:
        yield sse("error", {"code": stop.code})
    except httpx.HTTPError, websockets.WebSocketException, OSError:
        LOG.exception("an upstream service failed during a query")
        yield sse("error", {"code": "upstream_unavailable"})
    finally:
        deps.resolver.streams.get(principal.user_id, set()).discard(run.cut)
