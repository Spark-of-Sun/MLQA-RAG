from __future__ import annotations

from common.auth.jwt import SessionClaims
from fastapi import HTTPException, Request


def get_current_claims(request: Request) -> SessionClaims:
    """AuthMiddleware has already verified the token and attached claims
    to request.state before any router runs; this dependency just exposes
    them with a FastAPI-friendly signature for routers to depend on.
    """
    claims = getattr(request.state, "claims", None)
    if claims is None:
        # Should be unreachable — AuthMiddleware rejects unauthenticated
        # requests before routing. Defensive only.
        raise HTTPException(status_code=401, detail="not authenticated")
    return claims

