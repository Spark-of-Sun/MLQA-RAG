from __future__ import annotations

from common.auth.jwt import SessionClaims
from common.models import Action, AuditEvent
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_claims
from app.middleware.tenant_scope import enforce_scope
from app.state import AppState

router = APIRouter(tags=["audit"])


def _state(request: Request) -> AppState:
    return request.app.state.legalmed


@router.get("/audit", response_model=list[AuditEvent])
async def search_audit_log(
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
    claims: SessionClaims = Depends(get_current_claims),
):
    enforce_scope(claims, claims.tenant_id, None, Action.EXPORT)
    return await _state(request).audit_repo.search(tenant_id=claims.tenant_id, user_id=user_id, session_id=session_id)
