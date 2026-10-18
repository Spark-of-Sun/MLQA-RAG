
from __future__ import annotations

from fastapi import HTTPException

from common.auth.jwt import SessionClaims
from common.models import Action


def enforce_scope(
    claims: SessionClaims,
    tenant_id: str,
    matter_or_patient_id: str | None,
    action: Action,
) -> None:
    """Re-checked here at the Gateway and again at Retrieval (defense in
    depth, per docs/architecture.md §7). Raises HTTPException(403) if no
    role on the claims covers the requested scope.
    """
    if claims.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant mismatch")

    for role in claims.roles:
        if matter_or_patient_id is None:
            if role.tenant_id == tenant_id and (role.action == action or role.action == Action.ADMIN):
                return
        elif role.covers(tenant_id, matter_or_patient_id, action):
            return

    raise HTTPException(status_code=403, detail="not authorized for this matter/patient scope")


