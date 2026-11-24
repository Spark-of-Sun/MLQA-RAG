"""Gateway HTTP API. Called by the Next.js BFF, which attaches the user's Auth0 access token server-side.

Every /v1 route is guarded by `contracts/authz-matrix.yaml` (blueprint 5.2, 17.1): a role not listed gets 404 so
the route's existence is not revealed; a listed role whose membership is pending or suspended gets 403
`membership_not_active`. The app refuses to start if routes and matrix drift apart (G3.6).
"""

# No `from __future__ import annotations`: route signatures use the local alias `P`, which FastAPI must resolve.

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from audit import AuditService
from gateway import frozen
from gateway.conversations import Conversations
from gateway.production import ProductionServices, StepUpRequired, register_production_routes
from gateway.query_flow import QueryFlow
from gateway.trust import needs_step_up, step_up_challenge
from generation import GenerationService
from identity import IdentityService
from identity.ratelimit import SlidingWindow
from ingestion import create_ingestion
from lmqa_auth import TokenVerifier, Unauthorized
from lmqa_db import Database
from lmqa_keys import field_cipher_from_settings
from lmqa_models.contracts import authz_matrix, feature_enabled, features, route_rules
from lmqa_models.errors import ServiceError
from lmqa_models.principal import Principal
from lmqa_models.settings import ConfigError, Settings, load_settings
from retrieval import create_retrieval

log = logging.getLogger("gateway")
MATRIX = authz_matrix()
RULES = route_rules()
NOT_FOUND = (
    "Not Found"  # Starlette's body for a path with no route, so a hidden route looks the same (R-2)
)


class CreateOrg(BaseModel):
    name: str = Field(max_length=200)
    kind: Literal["legal", "medical", "both"]


class JoinAdmin(BaseModel):
    code: str = Field(max_length=200)
    workspace_name: str = Field(max_length=200)


class CodeBody(BaseModel):
    code: str = Field(max_length=200)


class Ask(BaseModel):
    question: str = Field(max_length=4000)
    conversation_id: UUID | None = None


class Rename(BaseModel):
    title: str = Field(max_length=200)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=60)


class Services:
    def __init__(self, settings: Settings, verifier: TokenVerifier | None) -> None:
        self.settings = settings
        self.db = Database(settings)
        self.verifier = verifier or TokenVerifier(settings)
        # One field cipher (and key cache) for the process; a workspace without a content key gets one from
        # identity, which holds the key-table grants (R-51.2).
        self.keys = field_cipher_from_settings()
        self.identity = IdentityService(settings, self.db, self.keys)
        self.keys.set_provisioner(self.identity.ensure_keys)
        self.documents, self.ingestor = create_ingestion(settings, self.db, keys=self.keys)
        self.generation = GenerationService(settings)
        self.retrieval = create_retrieval(settings, self.db, self.keys, self.generation.reranker)
        self.queries = QueryFlow(settings, self.db, self.retrieval, self.generation, self.keys)
        self.conversations = Conversations(self.db, self.queries)
        self.audit = AuditService(self.db, self.keys)
        self.query_limit = SlidingWindow(settings.queries_per_minute, 60)
        self.upload_limit = SlidingWindow(60, 60)
        self.production = ProductionServices(settings, self)
        self.policy = self.production.policy


def create_app(  # noqa: C901, PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
    settings: Settings | None = None,
    *,
    verifier: TokenVerifier | None = None,
    resume_jobs: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    svc = Services(settings, verifier)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        svc.db.open()
        svc.production.start()  # revocation consumer (Valkey pub/sub)
        svc.retrieval.warm()  # load a local re-ranker in the background (nothing to load for RERANK_MODEL=llm)
        if resume_jobs and (n := svc.ingestor.resume_pending()):
            log.info("resumed %d pending ingestion job(s)", n)
        if not svc.generation.configured:
            log.warning(
                "no answer model is configured (%s): questions will fail",
                ", ".join(svc.generation.client.missing()),
            )
        if not settings.gemini_api_key:
            log.warning(
                "GEMINI_API_KEY is not set: uploads and search (Gemini embeddings) will fail until it is"
            )
        yield
        svc.ingestor.shutdown()
        svc.db.close()

    app = FastAPI(
        title="LMQA Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env == "local" else None,
        redoc_url=None,
    )
    app.state.services = svc

    # ------------------------------------------------------------------ errors
    @app.exception_handler(StepUpRequired)
    async def _step_up(_: Request, exc: StepUpRequired) -> JSONResponse:
        return step_up_challenge("passkey", exc.max_age)

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        if exc.status >= 500:
            log.warning("unavailable: %s", exc.message)
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(psycopg.OperationalError)
    async def _db_down(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
        log.error("database unavailable: %s", type(exc).__name__)
        return JSONResponse({"detail": "Database unavailable."}, status_code=503)

    # ------------------------------------------------------------------ the route guard
    def guard(request: Request) -> Principal | None:
        route = request.scope.get("route")
        key = (request.method, getattr(route, "path", ""))
        roles = MATRIX.get(key)
        if roles is None or not feature_enabled(RULES[key].feature):
            # A disabled feature's endpoints do not exist (18): same status and body as a path with no route.
            raise HTTPException(404, NOT_FOUND)
        if "public" in roles:
            return None
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        token = header[7:].strip()
        try:
            claims = svc.verifier.verify(token)
        except Unauthorized as exc:
            log.info("token rejected: %s", exc)
            raise HTTPException(
                401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"}
            ) from None
        request.state.claims = claims
        email, name = claims.email, claims.name
        if email is None and not svc.identity.known_email(claims.sub):
            email, name = svc.verifier.userinfo(token)
        p = svc.identity.resolve(claims.sub, email, name or claims.name)
        if "authenticated" in roles:
            return p
        m = p.membership
        if m is None or m.role not in roles:
            raise HTTPException(404, NOT_FOUND)
        if not m.active:
            raise HTTPException(403, "membership_not_active")
        if RULES[key].step_up and needs_step_up(
            claims.auth_strength,
            claims.auth_time,
            required="passkey",
            max_age=svc.policy.step_up_max_age,
        ):
            raise StepUpRequired(svc.policy.step_up_max_age)
        return p

    def principal(p: Annotated[Principal | None, Depends(guard)]) -> Principal:
        assert p is not None
        return p

    P = Annotated[Principal, Depends(principal)]

    def client_ip(request: Request) -> str:
        host = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for", "")
        if host in {"127.0.0.1", "::1"} and forwarded:  # only the local BFF may name the client
            return forwarded.split(",")[0].strip()
        return host

    # Every path operation runs the guard (FastAPI caches it per request, so `P` reuses the result).
    app.router.dependencies.append(Depends(guard))

    # ------------------------------------------------------------------ health and me
    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        svc.db.ping()
        return {
            "status": "ok",
            "llm_configured": svc.generation.configured,
            "model": svc.generation.client.model,
            "reranker": svc.retrieval.reranker.model if svc.retrieval.reranker else None,
            # The public website has no signed-in user to read /v1/me from; it reads this flag (frozen, DEV-21).
            "public_site": feature_enabled("public_site"),
        }

    @app.get("/v1/me")
    def me(p: P) -> dict[str, Any]:
        # Enabled feature flags let the UI hide screens whose routes answer 404 (convenience, not control).
        return {**svc.identity.me(p), "features": sorted(n for n, on in features().items() if on)}

    @app.get("/v1/profile")
    def profile(p: P) -> dict[str, Any]:
        return svc.identity.profile(p)

    @app.patch("/v1/profile")
    def update_profile(p: P, body: ProfileUpdate) -> dict[str, Any]:
        return svc.identity.update_profile(p, body.model_dump(exclude_unset=True))

    # ------------------------------------------------------------------ onboarding (blueprint 7)
    @app.post("/v1/onboarding/organization", status_code=201)
    def create_org(p: P, body: CreateOrg) -> dict[str, Any]:
        return svc.identity.create_organization(p, body.name, body.kind)

    @app.post("/v1/onboarding/join-admin", status_code=201)
    def join_admin(p: P, body: JoinAdmin, request: Request) -> dict[str, Any]:
        return svc.identity.join_admin(p, client_ip(request), body.code, body.workspace_name)

    @app.post("/v1/onboarding/preview-tenant")
    def preview_tenant(p: P, body: CodeBody, request: Request) -> dict[str, Any]:
        return svc.identity.preview_tenant(p, client_ip(request), body.code)

    @app.post("/v1/onboarding/join-tenant", status_code=201)
    def join_tenant(p: P, body: CodeBody, request: Request) -> dict[str, Any]:
        return svc.identity.join_tenant(p, client_ip(request), body.code)

    @app.delete("/v1/onboarding/request", status_code=204)
    def withdraw(p: P) -> None:
        svc.identity.withdraw(p)

    # ------------------------------------------------------------------ Super Admin
    @app.get("/v1/org/admins")
    def list_admins(p: P) -> list[dict[str, Any]]:
        return frozen.admin_rows(svc.identity.list_admins(p))

    @app.post("/v1/org/admins/{membership_id}/{action}")
    def decide_admin(p: P, membership_id: UUID, action: str) -> dict[str, Any]:
        return svc.identity.decide_admin(p, str(membership_id), action)

    @app.get("/v1/org/code")
    def org_code(p: P) -> dict[str, Any] | None:
        return svc.identity.code_info(p, "org")

    @app.post("/v1/org/code", status_code=201)
    def rotate_org_code(p: P) -> dict[str, Any]:
        return svc.identity.generate_code(p, "org")

    # ------------------------------------------------------------------ Admin
    @app.get("/v1/workspace/members")
    def list_members(p: P) -> list[dict[str, Any]]:
        return frozen.member_rows(svc.identity.list_members(p))

    @app.post("/v1/workspace/members/{membership_id}/{action}")
    def decide_member(p: P, membership_id: UUID, action: str) -> dict[str, Any]:
        return svc.identity.decide_member(p, str(membership_id), action)

    @app.get("/v1/workspace/code")
    def admin_code(p: P) -> dict[str, Any] | None:
        return svc.identity.code_info(p, "admin")

    @app.post("/v1/workspace/code", status_code=201)
    def rotate_admin_code(p: P) -> dict[str, Any]:
        return svc.identity.generate_code(p, "admin")

    # ------------------------------------------------------------------ documents
    @app.get("/v1/documents")
    def list_documents(p: P) -> list[dict[str, Any]]:
        return svc.documents.list(p)

    @app.post("/v1/documents", status_code=201)
    def upload(
        p: P,
        file: Annotated[UploadFile, File()],
        visibility: Annotated[str | None, Form()] = None,
        title: Annotated[str | None, Form(max_length=200)] = None,
        share_with: Annotated[list[str] | None, Form()] = None,
    ) -> dict[str, Any]:
        if svc.upload_limit.hit(p.user_id):
            raise HTTPException(429, "Too many uploads. Try again in a minute.")
        data = file.file.read(settings.upload_max_mb * 1024 * 1024 + 1)
        return svc.documents.upload(
            p, file.filename or "upload", data, visibility, title, share_with
        )

    @app.get("/v1/documents/{doc_id}")
    def get_document(p: P, doc_id: UUID) -> dict[str, Any]:
        return svc.documents.get(p, str(doc_id))

    @app.delete("/v1/documents/{doc_id}", status_code=204)
    def delete_document(p: P, doc_id: UUID) -> None:
        svc.documents.delete(p, str(doc_id))

    # ------------------------------------------------------------------ questions and chats
    @app.post("/v1/queries")
    def ask(p: P, body: Ask) -> dict[str, Any]:
        if svc.query_limit.hit(p.user_id):
            raise HTTPException(429, "Too many questions. Try again in a minute.")
        conversation = str(body.conversation_id) if body.conversation_id else None
        return svc.queries.ask(p, body.question, conversation)

    @app.get("/v1/queries/{query_id}")
    def get_query(p: P, query_id: UUID) -> dict[str, Any]:
        result = svc.queries.get(p, str(query_id))
        if result is None:
            raise HTTPException(404, "Not found")
        return result

    @app.get("/v1/conversations")
    def list_conversations(
        p: P, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ) -> list[dict[str, Any]]:
        return svc.conversations.list(p, limit)

    @app.get("/v1/conversations/{conversation_id}")
    def get_conversation(p: P, conversation_id: UUID) -> dict[str, Any]:
        return svc.conversations.get(p, str(conversation_id))

    @app.patch("/v1/conversations/{conversation_id}")
    def rename_conversation(p: P, conversation_id: UUID, body: Rename) -> dict[str, Any]:
        return svc.conversations.rename(p, str(conversation_id), body.title)

    @app.delete("/v1/conversations/{conversation_id}", status_code=204)
    def delete_conversation(p: P, conversation_id: UUID) -> None:
        svc.conversations.delete(p, str(conversation_id))

    # ------------------------------------------------------------------ audit
    @app.get("/v1/audit")
    def audit_events(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        p: P,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        before: Annotated[int | None, Query(ge=1)] = None,
        category: Annotated[str | None, Query(max_length=40)] = None,
        action: Annotated[str | None, Query(max_length=80)] = None,
        actor: Annotated[str | None, Query(max_length=40)] = None,
        since: Annotated[datetime | None, Query()] = None,
        until: Annotated[datetime | None, Query()] = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
    ) -> list[dict[str, Any]]:
        return svc.audit.events(
            p,
            limit,
            before,
            category=category,
            action=action,
            actor=actor,
            since=since,
            until=until,
            q=q,
        )

    @app.get("/v1/audit/verify")
    def audit_verify(p: P) -> dict[str, Any]:
        return svc.audit.verify(p)

    register_production_routes(app, svc, P)
    _check_matrix_drift(app)
    return app


def _check_matrix_drift(app: FastAPI) -> None:
    """Refuse to start when code and contracts/authz-matrix.yaml disagree (G3.6)."""
    in_code = {
        (method, r.path)
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/v1")
        for method in r.methods
    }
    in_matrix = set(MATRIX)
    if in_code != in_matrix:
        missing = sorted(in_code - in_matrix)
        extra = sorted(in_matrix - in_code)
        raise RuntimeError(
            f"authz-matrix drift: routes without a matrix entry {missing}; matrix entries without a route {extra}"
        )
