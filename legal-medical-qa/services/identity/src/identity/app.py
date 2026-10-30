"""The identity HTTP API (doc 15.2 to 15.6): onboarding, organization and workspace management.

Every route re-checks the caller's role from the verified context token (defense in depth: the
Gateway's allow-list already refused other roles), and every failure that must not reveal
anything has one body: a bad code is always ``400 Code invalid or expired``; a resource outside
the caller's scope is ``404``. The client address comes from the Gateway (the only caller).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from identity.codes import CodeRejected
from identity.domain import ConflictError, Identity, NotFoundError
from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims, problem

LOG = logging.getLogger("identity")
Claims = Annotated[ContextClaims, Depends(context_claims())]
WriteClaims = Annotated[ContextClaims, Depends(context_claims(state_changing=True))]
ClientIp = Annotated[str | None, Header(alias="x-client-ip")]


class OrgIn(BaseModel):
    """Create an organization."""

    name: str = Field(min_length=2, max_length=120)
    deployment_type: str = Field(pattern="^(legal|medical|both)$")
    region: str = Field(default="us", max_length=16)


class CodeIn(BaseModel):
    """A pasted code; the server normalizes and checks it."""

    code: str = Field(max_length=200)


class GrantIn(BaseModel):
    """One matter grant with a tier ceiling and an optional expiry."""

    matter_id: UUID
    max_tier: int = Field(ge=1, le=4)
    expires_at: datetime | None = None


class DecisionIn(BaseModel):
    """Optional grants applied at tenant approval."""

    grants: list[GrantIn] = Field(default_factory=list[GrantIn])


class MatterIn(BaseModel):
    """A matter or patient scope."""

    label: str = Field(min_length=1, max_length=200)
    type: str = Field(default="matter", pattern="^(matter|patient)$")


class WallIn(BaseModel):
    """An ethical wall."""

    user_id: UUID
    matter_id: UUID
    reason_code: str = Field(min_length=1, max_length=60)


def _only(claims: ContextClaims, role: str) -> None:
    if claims.role != role:
        raise NotFoundError


def create_app(identity: Identity, verifier: ContextVerifier) -> FastAPI:  # noqa: C901, PLR0915 - one route table
    """Build the app around the domain object and this service's own token verifier."""
    app = FastAPI(title="identity", docs_url=None, redoc_url=None)
    app.state.verifier = verifier

    @app.exception_handler(CodeRejected)
    async def _bad_code(_r: Request, _e: CodeRejected) -> JSONResponse:
        return problem(400, "Code invalid or expired")

    @app.exception_handler(NotFoundError)
    async def _missing(request: Request, _e: NotFoundError) -> JSONResponse:
        LOG.info(
            "404 for %s %s (outside scope, wrong role or absent)", request.method, request.url.path
        )
        return problem(404, "Not Found")

    @app.exception_handler(ConflictError)
    async def _conflict(_r: Request, e: ConflictError) -> JSONResponse:
        return problem(409, "Conflict", detail=str(e))

    def onboarding(claims: ContextClaims) -> str:
        if not claims.is_onboarding or not claims.auth0_sub:
            raise NotFoundError
        return claims.auth0_sub

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # onboarding (audience "onboarding": the caller has no membership yet)
    @app.post("/internal/v1/onboarding/organization", status_code=201)
    async def create_org(body: OrgIn, claims: WriteClaims) -> dict[str, Any]:
        return await identity.create_organization(
            onboarding(claims), body.name, body.deployment_type, body.region
        )

    @app.post("/internal/v1/onboarding/join-admin", status_code=202)
    async def join_admin(body: CodeIn, claims: WriteClaims, ip: ClientIp = None) -> dict[str, str]:
        return await identity.join_admin(onboarding(claims), body.code, ip)

    @app.post("/internal/v1/onboarding/join-tenant/preview")
    async def preview(body: CodeIn, claims: WriteClaims, ip: ClientIp = None) -> dict[str, Any]:
        return await identity.preview_tenant_code(onboarding(claims), body.code, ip)

    @app.post("/internal/v1/onboarding/join-tenant", status_code=202)
    async def join_tenant(body: CodeIn, claims: WriteClaims, ip: ClientIp = None) -> dict[str, str]:
        return await identity.join_tenant(onboarding(claims), body.code, ip)

    @app.get("/internal/v1/onboarding/status")
    async def status(claims: Claims) -> dict[str, Any]:
        return await identity.status(onboarding(claims))

    @app.get("/internal/v1/me")
    async def me(claims: Claims) -> dict[str, Any]:
        return await identity.me(claims.db_context())

    # organization (Super Admin)
    @app.get("/internal/v1/org")
    async def org(claims: Claims) -> dict[str, Any]:
        _only(claims, "super_admin")
        return await identity.me(claims.db_context())

    @app.post("/internal/v1/org/code", status_code=201)
    @app.post("/internal/v1/org/code/rotate", status_code=201)
    async def org_code(claims: WriteClaims) -> dict[str, str]:
        _only(claims, "super_admin")
        return {
            "code": await identity.generate_org_code(claims.db_context())
        }  # shown once, never stored

    @app.get("/internal/v1/org/admins")
    async def admins(claims: Claims) -> dict[str, Any]:
        _only(claims, "super_admin")
        return {"admins": await identity.list_admins(claims.db_context())}

    @app.get("/internal/v1/org/admins/{admin_id}")
    async def admin(admin_id: UUID, claims: Claims) -> dict[str, Any]:
        _only(claims, "super_admin")
        for item in await identity.list_admins(claims.db_context()):
            if item["user_id"] == str(admin_id):
                return item
        raise NotFoundError

    # One explicit route per action (doc 15.4): each is allow-listed and step-up-gated by itself.
    def admin_action(action: str):  # noqa: ANN202 - returns the route handler
        async def handler(admin_id: UUID, claims: WriteClaims) -> dict[str, str]:
            _only(claims, "super_admin")
            return await identity.decide_admin(claims.db_context(), admin_id, action)

        handler.__name__ = f"{action}_admin"
        return handler

    for _action in ("approve", "reject", "suspend", "reactivate"):
        app.post(f"/internal/v1/org/admins/{{admin_id}}/{_action}")(admin_action(_action))

    @app.get("/internal/v1/org/workspaces")
    async def workspaces(claims: Claims) -> dict[str, Any]:
        _only(claims, "super_admin")
        return {
            "workspaces": [
                {
                    k: a[k]
                    for k in ("workspace_id", "workspace_state", "tenant_count", "document_count")
                }
                for a in await identity.list_admins(claims.db_context())
            ]
        }

    # The workspace admin's routes
    @app.get("/internal/v1/workspace/policy")
    async def get_policy(claims: Claims) -> dict[str, Any]:
        _only(claims, "admin")
        return await identity.get_policy(claims.db_context())

    @app.patch("/internal/v1/workspace/policy")
    async def patch_policy(body: dict[str, Any], claims: WriteClaims) -> dict[str, Any]:
        _only(claims, "admin")
        return await identity.patch_policy(claims.db_context(), body)

    @app.post("/internal/v1/workspace/code", status_code=201)
    @app.post("/internal/v1/workspace/code/rotate", status_code=201)
    async def workspace_code(claims: WriteClaims) -> dict[str, str]:
        _only(claims, "admin")
        return {"code": await identity.generate_admin_code(claims.db_context())}

    @app.get("/internal/v1/workspace/tenants")
    async def tenants(claims: Claims) -> dict[str, Any]:
        _only(claims, "admin")
        return {"tenants": await identity.list_tenants(claims.db_context())}

    def tenant_action(action: str):  # noqa: ANN202 - returns the route handler
        async def handler(
            tenant_id: UUID, claims: WriteClaims, body: DecisionIn | None = None
        ) -> dict[str, str]:
            _only(claims, "admin")
            grants = [g.model_dump(mode="json") for g in body.grants] if body else None
            return await identity.decide_tenant(claims.db_context(), tenant_id, action, grants)

        handler.__name__ = f"{action}_tenant"
        return handler

    for _action in ("approve", "reject", "suspend", "reactivate"):
        app.post(f"/internal/v1/workspace/tenants/{{tenant_id}}/{_action}")(tenant_action(_action))

    @app.put(
        "/internal/v1/workspace/tenants/{tenant_id}/grants", status_code=204, response_model=None
    )
    async def put_grants(tenant_id: UUID, body: list[GrantIn], claims: WriteClaims) -> None:
        _only(claims, "admin")
        await identity.set_grants(
            claims.db_context(), tenant_id, [g.model_dump(mode="json") for g in body]
        )

    @app.get("/internal/v1/workspace/matters")
    async def matters(claims: Claims) -> dict[str, Any]:
        return {"matters": await identity.list_matters(claims.db_context())}

    @app.post("/internal/v1/workspace/matters", status_code=201)
    async def create_matter(body: MatterIn, claims: WriteClaims) -> dict[str, str]:
        _only(claims, "admin")
        return await identity.create_matter(claims.db_context(), body.label, body.type)

    @app.patch("/internal/v1/workspace/matters/{matter_id}", status_code=204, response_model=None)
    async def rename_matter(matter_id: UUID, body: MatterIn, claims: WriteClaims) -> None:
        _only(claims, "admin")
        await identity.rename_matter(claims.db_context(), matter_id, body.label)

    @app.delete("/internal/v1/workspace/matters/{matter_id}", status_code=204, response_model=None)
    async def delete_matter(matter_id: UUID, claims: WriteClaims) -> None:
        _only(claims, "admin")
        await identity.delete_matter(claims.db_context(), matter_id)

    @app.get("/internal/v1/workspace/walls")
    async def walls(claims: Claims) -> dict[str, Any]:
        _only(claims, "admin")
        return {"walls": await identity.list_walls(claims.db_context())}

    @app.post("/internal/v1/workspace/walls", status_code=201)
    async def create_wall(body: WallIn, claims: WriteClaims) -> dict[str, str]:
        _only(claims, "admin")
        await identity.create_wall(
            claims.db_context(), body.user_id, body.matter_id, body.reason_code
        )
        return {"status": "created"}

    return app
