"""Auth0 access-token verification.

Only RS256 access tokens for our API audience and issuer are accepted; `alg=none`, HS256 confusion, wrong
audience or issuer, expired or not-yet-valid tokens all raise `Unauthorized`, which the gateway turns into
one uniform 401 (G3.1). Role, workspace and status are never read from the token: they come from the
database on every request, so a suspension applies at the next request.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import jwt

from lmqa_models.settings import Settings


class Unauthorized(Exception):
    """Any token problem. The reason is for logs only."""


@dataclass(frozen=True)
class Claims:
    sub: str
    email: str | None
    name: str | None


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._jwks = jwt.PyJWKClient(settings.auth0_jwks_url, cache_keys=True, lifespan=3600, timeout=10)

    def verify(self, token: str) -> Claims:
        if not self._s.auth0_audience:
            raise Unauthorized("audience not configured")
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise Unauthorized("alg")
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._s.auth0_audience,
                issuer=self._s.auth0_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=30,
            )
        except Unauthorized:
            raise
        except (jwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
            raise Unauthorized(type(exc).__name__) from exc
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise Unauthorized("sub")
        ns = self._s.auth0_claims_namespace
        email = claims.get(f"{ns}/email") or claims.get("email")
        name = claims.get(f"{ns}/name") or claims.get("name")
        return Claims(sub, email if isinstance(email, str) else None, name if isinstance(name, str) else None)

    def userinfo(self, token: str) -> tuple[str | None, str | None]:
        """Email and name from Auth0 /userinfo (the token carries `openid`). Used once per new user."""
        if not self._s.auth0_domain:
            return None, None
        try:
            resp = httpx.get(
                f"https://{self._s.auth0_domain}/userinfo", headers={"Authorization": f"Bearer {token}"}, timeout=10
            )
        except httpx.HTTPError:
            return None, None
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        return data.get("email"), data.get("name") or data.get("nickname")
