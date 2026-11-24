"""Auth0 access-token verification.

Only RS256 access tokens for our API audience and issuer are accepted; `alg=none`, HS256 confusion, wrong
audience or issuer, expired or not-yet-valid tokens all raise `Unauthorized`, which the gateway turns into
one uniform 401 (G3.1). Role, workspace and status are never read from the token: they come from the
database on every request, so a suspension applies at the next request.

Two audiences (design 8.2, DEV-10): `main` carries the Auth0 Organization of the login and, once
`AUTH0_ORGANIZATIONS=on`, a `main` token without `org_id` is refused; `onboarding` is for people who have no
organization yet, so an `onboarding` token that carries an `org_id` is always refused. The post-login Action denies
both cases at Auth0 as well.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import jwt

from lmqa_auth.strength import PASSWORD, normalize
from lmqa_models.settings import Settings

MAIN = "main"
ONBOARDING = "onboarding"


class Unauthorized(Exception):
    """Any token problem. The reason is for logs only."""


@dataclass(frozen=True)
class Claims:
    sub: str
    email: str | None
    name: str | None
    # Authentication facts from the post-login Action (infra/auth0/actions/post-login.js); never authorization.
    org_id: str | None = None
    auth_strength: str = PASSWORD  # one of lmqa_auth.strength.AUTH_STRENGTHS
    amr: tuple[str, ...] = ()
    authenticator: str | None = None
    auth_time: int | None = None
    role_claim: str | None = (
        None  # only compared with the database role; a mismatch is denied and alerted
    )


def check_organization(audience: str, org_id: object, *, required: bool) -> None:
    """`onboarding` denies an organization; `main` requires one when Organizations are on."""
    has_org = isinstance(org_id, str) and bool(org_id)
    if audience == ONBOARDING and org_id is not None:
        raise Unauthorized("organization on onboarding audience")
    if audience == MAIN and required and not has_org:
        raise Unauthorized("organization required")


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._jwks = jwt.PyJWKClient(
            settings.auth0_jwks_url, cache_keys=True, lifespan=3600, timeout=10
        )

    def _audience(self, audience: str) -> str:
        value = {MAIN: self._s.auth0_audience, ONBOARDING: self._s.auth0_audience_onboarding}.get(
            audience
        )
        if not value:
            raise Unauthorized("audience not configured")
        return value

    def verify(self, token: str, audience: str = MAIN) -> Claims:
        expected = self._audience(audience)
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise Unauthorized("alg")
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=expected,
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
        strength = claims.get(f"{ns}/auth_strength")
        amr = claims.get(f"{ns}/amr") or claims.get("amr") or []
        org = claims.get("org_id") or claims.get(f"{ns}/org_id")
        check_organization(audience, org, required=self._s.auth0_organizations)
        auth_time = claims.get("auth_time")
        return Claims(
            sub,
            email if isinstance(email, str) else None,
            name if isinstance(name, str) else None,
            org_id=org if isinstance(org, str) else None,
            auth_strength=normalize(strength),
            amr=tuple(str(a) for a in amr) if isinstance(amr, list) else (),
            authenticator=str(claims.get(f"{ns}/authenticator") or "") or None,
            auth_time=int(auth_time) if isinstance(auth_time, int) else None,
            role_claim=str(claims.get(f"{ns}/role")) if claims.get(f"{ns}/role") else None,
        )

    def userinfo(self, token: str) -> tuple[str | None, str | None]:
        """Email and name from Auth0 /userinfo (the token carries `openid`). Used once per new user."""
        if not self._s.auth0_domain:
            return None, None
        try:
            resp = httpx.get(
                f"https://{self._s.auth0_domain}/userinfo",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
        except httpx.HTTPError:
            return None, None
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        return data.get("email"), data.get("name") or data.get("nickname")
