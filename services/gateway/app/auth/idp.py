from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from common.auth.jwt import create_session_jwt
from common.models import Action, RoleScope

dev_router = APIRouter(tags=["dev"])


class DevSessionRequest(BaseModel):
    user_id: str
    tenant_id: str
    matter_or_patient_id: str | None = None
    action: Action = Action.QUERY


class DevSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@dev_router.post("/session", response_model=DevSessionResponse)
async def mint_dev_session(body: DevSessionRequest) -> DevSessionResponse:
    """LOCAL DEV ONLY — mints a session JWT directly, bypassing NextAuth/
    the enterprise IdP, so the Gateway can be curled before the frontend
    exists. Only mounted when ENVIRONMENT=local (see app/main.py).
    """
    if os.environ.get("ENVIRONMENT", "local") != "local":
        raise HTTPException(status_code=404, detail="not found")

    role = RoleScope(
        tenant_id=body.tenant_id,
        matter_or_patient_id=body.matter_or_patient_id,
        action=body.action,
    )
    token = create_session_jwt(user_id=body.user_id, tenant_id=body.tenant_id, roles=[role])
    return DevSessionResponse(access_token=token)


def exchange_idp_code_for_claims(code: str) -> dict:
    """Placeholder for the real OIDC/SAML exchange with Okta/Azure AD (or
    the local oidc-provider mock). Not wired yet — NextAuth owns this
    exchange in frontend/lib/auth.ts for now; this gets called from there
    once the frontend exists.
    """
    raise NotImplementedError("IdP code exchange is owned by frontend/lib/auth.ts for now")
