"""Context tokens and signer certificates (doc 9.1, G3.3, G3.5).

The Gateway mints a 60 second ES256 JWT for exactly one target service. It signs with an
in-memory key that a KMS-held trust root has *certified* for at most one hour, so the KMS is
called about once per instance per hour and never per request (DEF-26). A compromised pod holds
a key that dies within the hour; revoking a pod is one deny-list entry. The Auth0 token is never
forwarded. Services build their database context from these claims only.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lmqa_db import ContextRole, DbContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lmqa_keys.signing import TrustRoot

TOKEN_LIFETIME_SECONDS: Final = 60
CERT_LIFETIME_SECONDS: Final = 3600
CLOCK_SKEW_SECONDS: Final = 5
ISSUER: Final = "lmqa-gateway"
CERT_ISSUER: Final = "lmqa-trust-root"
CERT_REFRESH_MARGIN_SECONDS: Final = 300
_REQUIRED: Final = ["exp", "iat", "iss", "aud", "sub", "jti"]


class ContextTokenError(Exception):
    """An internal token is not acceptable. Services answer 401 with a uniform body."""


class DenyList(Protocol):
    """Revoked signer certificates (backed by Valkey in services)."""

    async def is_denied(self, cert_id: str) -> bool:
        """True if the certificate has been revoked."""
        ...


class JtiStore(Protocol):
    """Single-use token IDs for state-changing calls (backed by Valkey in services)."""

    async def claim(self, jti: str, ttl_seconds: int) -> bool:
        """Record ``jti``; return False if it was already used."""
        ...


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class ContextClaims:
    """The verified principal for one internal call. This is all a service may rely on."""

    user_id: uuid.UUID
    org_id: uuid.UUID
    workspace_id: uuid.UUID | None
    role: str
    auth_strength: str | None
    scope_hash: str
    scope_version: int
    principal_version: int
    request_id: uuid.UUID
    jti: str
    audience: str
    issued_at: int
    auth0_sub: str | None = None
    """Only set for onboarding callers, who have no user row yet (role ``onboarding``)."""

    @property
    def is_onboarding(self) -> bool:
        """True for a caller who is authenticated but not yet a member of any organization."""
        return self.role == "onboarding"

    def db_context(self) -> DbContext:
        """The database context this principal runs queries as (never taken from the request)."""
        return DbContext(
            role=ContextRole(self.role),
            org_id=self.org_id,
            workspace_id=self.workspace_id,
            user_id=self.user_id,
        )


@dataclass(frozen=True, slots=True)
class Certificate:
    """A signer certificate: the trust root's signature over an ephemeral public key."""

    cert_id: str
    workload: str
    not_before: int
    not_after: int
    public_key_pem: str
    signature: bytes

    def payload(self) -> bytes:
        """Canonical bytes the trust root signs."""
        return json.dumps(
            {
                "v": 1,
                "iss": CERT_ISSUER,
                "kid": self.cert_id,
                "workload": self.workload,
                "nbf": self.not_before,
                "exp": self.not_after,
                "pub": self.public_key_pem,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def serialize(self) -> str:
        """Compact ``payload.signature`` form carried in the token header."""
        return f"{_b64e(self.payload())}.{_b64e(self.signature)}"

    @classmethod
    def parse(cls, text: str) -> Certificate:
        """Parse the compact form. Signature is *not* checked here."""
        try:
            payload_b64, signature_b64 = text.split(".")
            body = json.loads(_b64d(payload_b64))
            return cls(
                cert_id=str(body["kid"]),
                workload=str(body["workload"]),
                not_before=int(body["nbf"]),
                not_after=int(body["exp"]),
                public_key_pem=str(body["pub"]),
                signature=_b64d(signature_b64),
            )
        except (ValueError, KeyError, TypeError) as exc:
            msg = "malformed certificate"
            raise ContextTokenError(msg) from exc


class ContextSigner:
    """Mints context tokens with a certified ephemeral key (one per Gateway instance)."""

    def __init__(
        self,
        trust_root: TrustRoot,
        workload: str,
        *,
        cert_lifetime: int = CERT_LIFETIME_SECONDS,
        token_lifetime: int = TOKEN_LIFETIME_SECONDS,
    ) -> None:
        """Create a signer. Lifetimes are configuration; policy caps them (1 hour, 60 seconds)."""
        if not 0 < cert_lifetime <= CERT_LIFETIME_SECONDS:
            msg = f"certificate lifetime must be in (0, {CERT_LIFETIME_SECONDS}] seconds"
            raise ValueError(msg)
        if not 0 < token_lifetime <= TOKEN_LIFETIME_SECONDS:
            msg = f"token lifetime must be in (0, {TOKEN_LIFETIME_SECONDS}] seconds"
            raise ValueError(msg)
        self._root, self._workload, self._lifetime = trust_root, workload, cert_lifetime
        self._token_lifetime = token_lifetime
        self._key: ec.EllipticCurvePrivateKey | None = None
        self._cert: Certificate | None = None
        self.trust_root_calls = 0

    async def _certify(self) -> Certificate:
        key = ec.generate_private_key(ec.SECP256R1())
        now = int(time.time())
        pem = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        unsigned = Certificate(
            str(uuid.uuid4()),
            self._workload,
            now - CLOCK_SKEW_SECONDS,
            now + self._lifetime,
            pem,
            b"",
        )
        signature = await self._root.sign(unsigned.payload())
        self.trust_root_calls += 1
        cert = Certificate(
            unsigned.cert_id,
            unsigned.workload,
            unsigned.not_before,
            unsigned.not_after,
            pem,
            signature,
        )
        self._key, self._cert = key, cert
        return cert

    async def certificate(self) -> Certificate:
        """The current certificate, refreshing it shortly before expiry."""
        cert = self._cert
        if cert is None or cert.not_after - time.time() < min(
            CERT_REFRESH_MARGIN_SECONDS, self._lifetime / 2
        ):
            return await self._certify()
        return cert

    async def sign_bytes(self, data: bytes) -> tuple[str, bytes]:
        """Sign arbitrary bytes (a validator verdict) with the certified key.

        Returns ``(certificate, signature)``; the verifier checks the chain with
        ``ContextVerifier.verify_signature``.
        """
        cert = await self.certificate()
        assert self._key is not None  # noqa: S101 - set together with the certificate
        return cert.serialize(), self._key.sign(data, ec.ECDSA(hashes.SHA256()))

    async def mint(self, *, audience: str, claims: ContextClaims | dict[str, Any]) -> str:
        """Mint a token for one ``audience`` (a single service)."""
        cert = await self.certificate()
        assert self._key is not None  # noqa: S101 - set together with the certificate
        body = dict(claims) if isinstance(claims, dict) else _claims_to_dict(claims)
        now = int(time.time())
        body.update(
            iss=ISSUER,
            aud=audience,
            iat=now,
            exp=now + self._token_lifetime,
            jti=uuid.uuid4().hex,
        )
        return jwt.encode(
            body,
            self._key,
            algorithm="ES256",
            headers={"kid": cert.cert_id, "cert": cert.serialize(), "typ": "ctx+jwt"},
        )


def _claims_to_dict(c: ContextClaims) -> dict[str, Any]:
    return {
        "sub": str(c.user_id),
        "org_id": str(c.org_id),
        "workspace_id": str(c.workspace_id) if c.workspace_id else None,
        "role": c.role,
        "auth_strength": c.auth_strength,
        "scope_hash": c.scope_hash,
        "scope_version": c.scope_version,
        "pv": c.principal_version,
        "request_id": str(c.request_id),
        "auth0_sub": c.auth0_sub,
    }


class ContextVerifier:
    """Verifies context tokens inside a service."""

    def __init__(
        self,
        trusted_public_keys_pem: Sequence[bytes],
        *,
        service: str,
        deny_list: DenyList,
        jti_store: JtiStore,
        skew_seconds: int = CLOCK_SKEW_SECONDS,
    ) -> None:
        """``trusted_public_keys_pem`` holds both keys during a trust-root rotation overlap."""
        if not 0 <= skew_seconds <= CLOCK_SKEW_SECONDS:
            msg = f"clock skew must be in [0, {CLOCK_SKEW_SECONDS}] seconds"
            raise ValueError(msg)
        self._roots = [serialization.load_pem_public_key(k) for k in trusted_public_keys_pem]
        self._service, self._deny, self._jti = service, deny_list, jti_store
        self._skew = skew_seconds

    def _check_certificate(self, cert: Certificate) -> ec.EllipticCurvePublicKey:
        for root in self._roots:
            if not isinstance(root, ec.EllipticCurvePublicKey):
                continue
            try:
                root.verify(cert.signature, cert.payload(), ec.ECDSA(hashes.SHA256()))
                break
            except InvalidSignature:
                continue
        else:
            msg = "certificate was not signed by a trusted root"
            raise ContextTokenError(msg)
        now = time.time()
        if not cert.not_before <= now + self._skew or now > cert.not_after + self._skew:
            msg = "certificate is outside its validity window"
            raise ContextTokenError(msg)
        if cert.not_after - cert.not_before > CERT_LIFETIME_SECONDS + 2 * CLOCK_SKEW_SECONDS:
            msg = "certificate lifetime exceeds policy"
            raise ContextTokenError(msg)
        key = serialization.load_pem_public_key(cert.public_key_pem.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey):
            msg = "certificate key is not an EC key"
            raise ContextTokenError(msg)
        return key

    async def verify_signature(self, certificate: str, data: bytes, signature: bytes) -> str:
        """Check ``signature`` over ``data`` against a certified key. Returns the signer workload.

        Raises ``ContextTokenError`` if the certificate is untrusted, expired, revoked, or the
        signature does not match. The Gateway uses this on validator verdicts (doc 11.6).
        """
        try:
            cert = Certificate.parse(certificate)
            key = self._check_certificate(cert)
            denied = await self._deny.is_denied(cert.cert_id)
            if not denied:
                key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
        except ContextTokenError:
            raise
        except Exception as exc:
            msg = f"signature rejected: {type(exc).__name__}"
            raise ContextTokenError(msg) from exc
        if denied:
            msg = "certificate is revoked"
            raise ContextTokenError(msg)
        return cert.workload

    async def verify(self, token: str, *, state_changing: bool = False) -> ContextClaims:
        """Return verified claims or raise ``ContextTokenError`` (one outcome for every failure)."""
        try:
            return await self._verify(token, state_changing=state_changing)
        except ContextTokenError:
            raise
        except Exception as exc:
            msg = f"context token rejected: {type(exc).__name__}"
            raise ContextTokenError(msg) from exc

    async def _verify(self, token: str, *, state_changing: bool) -> ContextClaims:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "ES256" or "cert" not in header:
            msg = "unexpected algorithm or missing certificate"
            raise ContextTokenError(msg)
        cert = Certificate.parse(str(header["cert"]))
        if header.get("kid") != cert.cert_id:
            msg = "key id does not match the certificate"
            raise ContextTokenError(msg)
        key = self._check_certificate(cert)
        if await self._deny.is_denied(cert.cert_id):
            msg = "certificate is revoked"
            raise ContextTokenError(msg)
        body: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            audience=self._service,
            issuer=ISSUER,
            leeway=self._skew,
            options={"require": _REQUIRED},
        )
        if time.time() - int(body["iat"]) > TOKEN_LIFETIME_SECONDS + self._skew:
            msg = "token was issued too long ago"
            raise ContextTokenError(msg)
        if state_changing and not await self._jti.claim(
            str(body["jti"]), TOKEN_LIFETIME_SECONDS * 2
        ):
            msg = "token id was already used"
            raise ContextTokenError(msg)
        workspace = body.get("workspace_id")
        return ContextClaims(
            user_id=uuid.UUID(str(body["sub"])),
            org_id=uuid.UUID(str(body["org_id"])),
            workspace_id=uuid.UUID(str(workspace)) if workspace else None,
            role=str(body["role"]),
            auth_strength=body.get("auth_strength"),
            scope_hash=str(body["scope_hash"]),
            scope_version=int(body["scope_version"]),
            principal_version=int(body["pv"]),
            request_id=uuid.UUID(str(body["request_id"])),
            jti=str(body["jti"]),
            audience=self._service,
            issued_at=int(body["iat"]),
            auth0_sub=body.get("auth0_sub"),
        )
