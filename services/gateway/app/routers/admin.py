from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from common.auth.jwt import SessionClaims
from common.models import Action, Tenant

from app.auth.dependencies import get_current_claims
from app.schemas.requests import TenantCreateRequest
from app.state import AppState

router = APIRouter(tags=["admin"])


def _state(request: Request) -> AppState:
    return request.app.state.legalmed


def _require_admin(claims: SessionClaims) -> None:
    if not any(role.action == Action.ADMIN for role in claims.roles):
        raise HTTPException(status_code=403, detail="admin role required")


@router.get("/tenants", response_model=list[Tenant])
async def list_tenants(request: Request, claims: SessionClaims = Depends(get_current_claims)):
    _require_admin(claims)
    return await _state(request).tenant_repo.list_all()


@router.post("/tenants", response_model=Tenant, status_code=201)
async def create_tenant(
    body: TenantCreateRequest,
    request: Request,
    claims: SessionClaims = Depends(get_current_claims),
):
    _require_admin(claims)
    tenant = Tenant(tenant_id=str(uuid4()), name=body.name, industry=body.industry)
    return await _state(request).tenant_repo.create(tenant)
