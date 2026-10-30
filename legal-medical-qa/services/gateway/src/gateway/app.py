"""The Gateway HTTP layer (doc 8.5, 8.7, 15.1): the only public API of the platform.

Per request, in order: match the route in the allow-list (unknown, disabled or wrong-role is 404);
verify the Auth0 access token (one uniform 401); resolve the principal from the DATABASE (the
token's role claim is advisory and a mismatch is refused); require a phishing-resistant
authentication strength for privileged roles; require a fresh authentication for step-up routes
(RFC 9470 challenge); rate-limit; apply idempotency; then mint a one-audience 60-second context
token and forward. The user's Auth0 token is never forwarded.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from gateway.limits import Idempotency, RateLimiter, StoredResponse
from gateway.matrix import Matrix, Route
from gateway.principal import Principal, PrincipalResolver
from gateway.query import QueryDeps, run_query
from lmqa_auth import ContextClaims, ContextSigner, TokenRejectedError, TokenVerifier, VerifiedToken
from lmqa_auth.web import problem
from lmqa_db import ContextRole, DbContext

LOG = logging.getLogger("gateway")
STRONG: Final = frozenset({"passkey", "webauthn_mfa"})
PRIVILEGED: Final = frozenset({"SA", "AD"})
STEP_UP_MAX_AGE: Final = 300
HOP_BY_HOP: Final = frozenset(
    {"connection", "keep-alive", "transfer-encoding", "te", "upgrade", "content-length", "host"}
)
AUDIT_PATHS: Final = {
    "/v1/org/audit": "/internal/v1/events",
    "/v1/workspace/audit": "/internal/v1/events",
    "/v1/audit/me": "/internal/v1/events",
}
UNAUTHORIZED: Final = {"type": "about:blank", "title": "Unauthorized", "status": 401}


class QueryIn(BaseModel):
    """A question, optionally narrowed to matters the caller can already read."""

    question: str = Field(min_length=1, max_length=2000)
    matter_ids: list[UUID] | None = None


@dataclass(slots=True)
class GatewayComponents:
    """Everything the Gateway holds. It has no storage, vector or decryption capability."""

    matrix: Matrix
    main_verifier: TokenVerifier
    onboarding_verifier: TokenVerifier
    principals: PrincipalResolver
    limiter: RateLimiter
    idempotency: Idempotency
    signer: ContextSigner
    http: httpx.AsyncClient
    query: QueryDeps
    services: dict[str, str]
    trust_cloudflare: bool = True
    background: list[asyncio.Task[None]] = field(default_factory=list[asyncio.Task[None]])


def unauthorized(challenge: str | None = None) -> JSONResponse:
    """The one 401 body for every authentication failure (a step-up adds only a header)."""
    headers = {"WWW-Authenticate": challenge or "Bearer"}
    return JSONResponse(
        UNAUTHORIZED, status_code=401, media_type="application/problem+json", headers=headers
    )


def step_up_challenge() -> str:
    """The RFC 9470 challenge asking the BFF for a fresh, strong authentication."""
    return (
        'Bearer error="insufficient_user_authentication", '
        'error_description="A fresh authentication is required", '
        f"max_age={STEP_UP_MAX_AGE}"
    )


def client_ip(request: Request, *, trust_cloudflare: bool) -> str | None:
    """The caller's address: Cloudflare's header only when we are known to sit behind it."""
    if trust_cloudflare and (cf := request.headers.get("cf-connecting-ip")):
        return cf
    return request.client.host if request.client else None


def create_app(c: GatewayComponents) -> FastAPI:  # noqa: C901, PLR0915 - one request pipeline
    """Build the Gateway app around constructed components."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        c.background.append(asyncio.create_task(c.principals.listen()))  # revocation consumer
        try:
            yield
        finally:
            for task in c.background:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

    def tokens_for(principal: Principal | None, verified: VerifiedToken) -> ContextClaims:
        if (
            principal is None
        ):  # onboarding: no membership yet; the Auth0 subject travels in the token
            return ContextClaims(
                uuid.uuid5(uuid.NAMESPACE_URL, verified.sub),
                UUID(int=0),
                None,
                "onboarding",
                verified.auth_strength,
                "",
                0,
                0,
                uuid.uuid4(),
                "",
                "",
                0,
                auth0_sub=verified.sub,
            )
        return ContextClaims(
            principal.user_id,
            principal.org_id,
            principal.workspace_id,
            principal.role,
            verified.auth_strength,
            principal.scope_hash,
            principal.scope_version,
            principal.principal_version,
            uuid.uuid4(),
            "",
            "",
            0,
        )

    async def proxy(
        route: Route, request: Request, claims: ContextClaims, ip: str | None
    ) -> Response:
        base = c.services[route.service]
        target = AUDIT_PATHS.get(route.path, "/internal" + request.url.path)
        query = f"?{request.url.query}" if request.url.query else ""
        headers = {
            k: v for k, v in request.headers.items() if k.lower() in {"content-type", "accept"}
        }
        headers["Authorization"] = "Bearer " + await c.signer.mint(
            audience=route.service, claims=claims
        )
        headers["X-Request-Id"] = str(claims.request_id)
        if ip:
            headers["X-Client-IP"] = ip
        try:
            upstream = await c.http.send(
                c.http.build_request(
                    request.method,
                    base + target + query,
                    headers=headers,
                    content=await request.body(),
                ),
                stream=True,
            )
        except httpx.HTTPError:
            LOG.exception("upstream %s is unavailable", route.service)
            return problem(502, "Upstream unavailable")  # fail closed with a stable error

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        out = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() != "content-encoding"
        }
        return StreamingResponse(body(), status_code=upstream.status_code, headers=out)

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}  # liveness only: no detail

    @app.api_route(
        "/v1/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], response_model=None
    )
    async def gateway(rest: str, request: Request) -> Response:  # noqa: C901, PLR0911, PLR0912
        path = "/v1/" + rest
        route = c.matrix.match(request.method, path)
        not_found = problem(404, "Not Found")
        if route is None:
            return not_found
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return unauthorized()
        verifier = c.onboarding_verifier if route.audience == "onboarding" else c.main_verifier
        try:
            verified = await asyncio.to_thread(verifier.verify, token)
        except TokenRejectedError:
            return unauthorized()
        ip = client_ip(request, trust_cloudflare=c.trust_cloudflare)
        principal: Principal | None = None
        if route.audience == "onboarding":
            if "ON" not in route.roles:
                return not_found
            subject = uuid.uuid5(uuid.NAMESPACE_URL, verified.sub)
        else:
            principal = await c.principals.resolve(verified.sub, verified.org_id)
            if principal is None:
                return unauthorized()
            if verified.advisory_role and verified.advisory_role != principal.role:
                LOG.warning(
                    "role claim mismatch for %s: token says %s, database says %s",
                    principal.user_id,
                    verified.advisory_role,
                    principal.role,
                )  # an alert, and a denial
                return unauthorized()
            role_code = principal.role_code
            if role_code == "BLOCKED":
                return unauthorized()  # suspended, rejected or removed: fail closed, reveal nothing
            if (
                role_code in PRIVILEGED
                and route.path != "/v1/me"
                and verified.auth_strength not in STRONG
            ):
                return unauthorized(
                    step_up_challenge()
                )  # privileged roles need a passkey or WebAuthn factor
            if not c.matrix.allows(route, role_code):
                return not_found
            if route.step_up:
                fresh = (verified.auth_time or verified.issued_at) >= time.time() - STEP_UP_MAX_AGE
                if not fresh or (role_code in PRIVILEGED and verified.auth_strength not in STRONG):
                    return unauthorized(step_up_challenge())
            subject = principal.user_id
        if not await c.limiter.allow(subject):
            return problem(429, "Too Many Requests")
        claims = tokens_for(principal, verified)
        idem_key = request.headers.get("idempotency-key")
        fingerprint = ""
        if idem_key and route.state_changing and not route.stream:
            fingerprint = c.idempotency.fingerprint(
                request.method, request.url.path, await request.body()
            )
            state, stored = await c.idempotency.begin(subject, idem_key, fingerprint)
            if state == "replay" and stored:
                return Response(
                    stored.body,
                    status_code=stored.status,
                    media_type=stored.content_type,
                    headers={"Idempotent-Replay": "true"},
                )
            if state in {"conflict", "busy"}:
                return problem(409 if state == "busy" else 422, "Idempotency-Key reuse conflict")
        if route.path == "/v1/query" and principal is not None:
            return await handle_query(request, principal)
        response = await proxy(route, request, claims, ip)
        if fingerprint and idem_key:
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            await c.idempotency.finish(
                subject,
                idem_key,
                fingerprint,
                StoredResponse(
                    response.status_code,
                    response.headers.get("content-type", "application/json"),
                    body,
                ),
            )
            return Response(
                body,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )
        return response

    async def handle_query(request: Request, principal: Principal) -> Response:
        body = QueryIn.model_validate_json(await request.body())
        ctx = DbContext(
            role=ContextRole(principal.role),
            org_id=principal.org_id,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
        )
        last = request.headers.get("last-event-id")
        if last:  # resume: only already released, audited sentences are replayed
            request_id, _, number = last.rpartition(":")
            try:
                frames = await c.query.resume.after(
                    UUID(request_id), principal.user_id, int(number)
                )
            except ValueError:
                frames = []

            async def replay() -> AsyncIterator[bytes]:
                for frame in frames:
                    yield frame

            return StreamingResponse(
                replay(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
            )
        stream: AsyncIterator[bytes] = run_query(c.query, principal, ctx, body.question)
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "Content-Encoding": "identity",
            },
        )

    app.state.components = c
    return app


__all__: list[Any] = ["GatewayComponents", "create_app", "step_up_challenge", "unauthorized"]
