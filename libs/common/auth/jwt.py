from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import jwt
from pydantic import BaseModel

from ..models.tenant import RoleScope

_ALGORITHM = "HS256"  # swap to RS256 + enterprise IdP's JWKS in production


class SessionClaims(BaseModel):
    """Decoded, verified contents of the short-lived session JWT that the
    Next.js BFF attaches to every request to the Gateway.
    """

    user_id: str
    tenant_id: str
    roles: list[RoleScope]
    exp: int


class JWTError(Exception):
    pass


def _secret() -> str:
    secret = os.environ.get("APP_SECRET_KEY")
    if not secret:
        raise JWTError("APP_SECRET_KEY is not set")
    return secret


def create_session_jwt(
    user_id: str,
    tenant_id: str,
    roles: list[RoleScope],
    ttl_seconds: int = 900,
) -> str:
    """Issues a short-lived session JWT. Called by the auth provider
    (NextAuth credentials callback, or the gateway's /auth/session route
    when using the local OIDC mock) — never by a downstream service.
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": [r.model_dump(mode="json") for r in roles],
        "iat": now,
        "exp": now + ttl_seconds,
        "iss": os.environ.get("JWT_ISSUER", "legalmed-local"),
        "aud": os.environ.get("JWT_AUDIENCE", "legalmed-services"),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_session_jwt(token: str) -> SessionClaims:
    """Verifies signature, issuer, audience and expiry. Raises JWTError on
    any failure — callers (gateway auth middleware) should turn this into
    a 401/403, never fall back to an unauthenticated path.
    """
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            audience=os.environ.get("JWT_AUDIENCE", "legalmed-services"),
            issuer=os.environ.get("JWT_ISSUER", "legalmed-local"),
        )
    except jwt.PyJWTError as exc:
        raise JWTError(str(exc)) from exc

    return SessionClaims(
        user_id=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=[RoleScope(**r) for r in payload.get("roles", [])],
        exp=payload["exp"],
    )


def seconds_until_expiry(claims: SessionClaims) -> float:
    return claims.exp - datetime.utcnow().timestamp()
