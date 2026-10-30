"""Verification of Auth0 access tokens at the Gateway (doc 8.5, G3.1).

Only RS256 is accepted, so ``alg=none`` and an HS256 token signed with the public key as an
HMAC secret (algorithm confusion) are rejected before any claim is read. The issuer must match
exactly, the audience must equal the API identifier (which also rejects ID tokens used as access
tokens), the authorized party must be an allowed client, ``exp`` and ``nbf`` are checked with at
most 30 seconds of skew, and ``org_id`` must be present. Every failure raises the same
``TokenRejectedError``, so the HTTP response is byte-identical whatever went wrong.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Final

import jwt
from jwt import PyJWKClient

ALLOWED_ALGORITHMS: Final = ("RS256",)
MAX_LEEWAY_SECONDS: Final = 30
JWKS_MIN_REFRESH_SECONDS: Final = 60.0


class TokenRejectedError(Exception):
    """The token is not acceptable; the caller logs why and never shows the client."""


@dataclass(frozen=True, slots=True)
class Auth0Settings:
    """What the Gateway trusts. All values come from configuration."""

    domain: str
    audience: str
    allowed_clients: frozenset[str]
    claims_namespace: str
    require_org: bool = True
    """False only for the onboarding API, whose Auth0 organization setting is 'deny'."""

    @property
    def issuer(self) -> str:
        """The exact ``iss`` value (with the trailing slash Auth0 uses)."""
        return f"https://{self.domain}/"

    @property
    def jwks_url(self) -> str:
        """Where the signing keys are published."""
        return f"https://{self.domain}/.well-known/jwks.json"


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """The only claims the platform trusts from Auth0: who, and which organization."""

    sub: str
    org_id: str
    azp: str
    auth_strength: str | None
    advisory_role: str | None
    issued_at: int
    auth_time: int | None
    raw: dict[str, Any]


class TokenVerifier:
    """Verify signatures against a JWKS and check every claim the design requires."""

    def __init__(self, settings: Auth0Settings, *, jwk_client: PyJWKClient | None = None) -> None:
        """Create a verifier; the JWKS is cached and refreshed at most once a minute."""
        self._settings = settings
        self._jwks = jwk_client or PyJWKClient(
            settings.jwks_url, cache_keys=True, lifespan=3600, timeout=5
        )
        self._last_refresh = 0.0

    def verify(self, token: str) -> VerifiedToken:
        """Return the verified token or raise ``TokenRejectedError``."""
        try:
            claims = self._decode(token)
        except TokenRejectedError:
            raise
        except Exception as exc:  # any parsing, signature or claim failure is one outcome
            msg = f"token rejected: {type(exc).__name__}"
            raise TokenRejectedError(msg) from exc
        return self._claims(claims)

    def _decode(self, token: str) -> dict[str, Any]:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            msg = f"algorithm {header.get('alg')!r} is not accepted"
            raise TokenRejectedError(msg)
        key = self._signing_key(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=list(ALLOWED_ALGORITHMS),
            audience=self._settings.audience,
            issuer=self._settings.issuer,
            leeway=MAX_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_nbf": True},
        )
        return claims

    def _signing_key(self, token: str) -> Any:  # noqa: ANN401 - PyJWT key type
        try:
            return self._jwks.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError:
            # An unknown kid may mean the keys rotated: refresh, but at most once a minute.
            now = time.monotonic()
            if now - self._last_refresh < JWKS_MIN_REFRESH_SECONDS:
                raise
            self._last_refresh = now
            self._jwks.get_jwk_set(refresh=True)
            return self._jwks.get_signing_key_from_jwt(token).key

    def _claims(self, claims: dict[str, Any]) -> VerifiedToken:
        org_id = claims.get("org_id")
        if self._settings.require_org and (not isinstance(org_id, str) or not org_id):
            msg = "missing org_id"
            raise TokenRejectedError(msg)
        if not self._settings.require_org and org_id:
            msg = "an organization-scoped token is not accepted by the onboarding API"
            raise TokenRejectedError(msg)
        org_id = org_id if isinstance(org_id, str) else ""
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp not in self._settings.allowed_clients:
            msg = "authorized party is not an allowed client"
            raise TokenRejectedError(msg)
        namespace = self._settings.claims_namespace.rstrip("/")
        strength = claims.get(f"{namespace}/auth_strength")
        role = claims.get(f"{namespace}/role")
        return VerifiedToken(
            sub=str(claims["sub"]),
            org_id=org_id,
            azp=azp,
            auth_strength=strength if isinstance(strength, str) else None,
            advisory_role=role if isinstance(role, str) else None,
            issued_at=int(claims["iat"]),
            auth_time=int(claims["auth_time"]) if "auth_time" in claims else None,
            raw=claims,
        )
