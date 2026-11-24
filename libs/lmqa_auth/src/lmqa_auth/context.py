"""Context tokens, signer certificates and signed job envelopes (blueprint 9.1 to 9.3, D29, G3.3, G3.5, G4.7).

Trust chain, without a KMS call per request:

    trust root (KMS asymmetric key, never exported)
      signs, about once per instance per hour -> SignerCertificate {kid, public JWK, issuer identity, nbf, exp}
        whose ephemeral ES256 private key signs, per call -> context token (JWT, one audience, 60 s, jti)

`TrustRoot` is a protocol with two real implementations: KMS (`lmqa_keys.AwsKmsProvider.sign`) in AWS
environments, and a locally generated P-256 key in dev/CI whose public half is the published trust bundle (the
same verification code runs in both). Verifiers hold the trust root's public key(s) and a deny list of revoked
certificate IDs (published on Valkey `revocation:signer`, applied within 2 s).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ISSUER = "lmqa-gateway"
TOKEN_TTL = 60
CERT_TTL = 3600
CLOCK_SKEW = 5
SERVICES = (
    "identity",
    "ingestion",
    "retrieval",
    "generation",
    "citation_validator",
    "audit",
    "ops",
)


class ContextTokenError(Exception):
    """Any verification failure. One message, so a caller learns nothing about which check failed."""

    def __init__(self, reason: str) -> None:
        super().__init__("invalid context token")
        self.reason = reason  # for logs and alerts only


class TrustRoot(Protocol):
    key_id: str

    def sign(self, message: bytes) -> bytes: ...  # DER ECDSA P-256 SHA-256
    def public_pem(self) -> bytes: ...


class LocalTrustRoot:
    """dev/CI trust root: a P-256 key held by the gateway process; its public PEM is the trust bundle."""

    def __init__(self, private_pem: bytes | None = None, key_id: str = "local-trust-root") -> None:
        self._key = (
            serialization.load_pem_private_key(private_pem, password=None)
            if private_pem
            else ec.generate_private_key(ec.SECP256R1())
        )
        if not isinstance(self._key, ec.EllipticCurvePrivateKey):
            raise TypeError("trust root must be an EC P-256 key")
        self.key_id = key_id

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message, ec.ECDSA(hashes.SHA256()))

    def public_pem(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )


class KmsTrustRoot:
    """Trust root in AWS KMS (ECC_NIST_P256, SIGN_VERIFY). One Sign call per signer certificate (G3.5)."""

    def __init__(self, provider: Any, key_ref: str) -> None:
        self._provider = provider
        self.key_id = key_ref
        self._public: bytes | None = None

    def sign(self, message: bytes) -> bytes:
        return self._provider.sign(self.key_id, message)

    def public_pem(self) -> bytes:
        if self._public is None:
            der = self._provider.public_key(self.key_id)
            key = serialization.load_der_public_key(der)
            self._public = key.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        return self._public


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class SignerCertificate:
    kid: str
    public_pem: bytes
    identity: str  # workload identity of the instance that holds the private key (gateway, citation_validator)
    nbf: int
    exp: int
    root_kid: str
    signature: bytes

    def body(self) -> bytes:
        return json.dumps(
            {
                "kid": self.kid,
                "pub": self.public_pem.decode(),
                "id": self.identity,
                "nbf": self.nbf,
                "exp": self.exp,
                "root": self.root_kid,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def encode(self) -> str:
        return _b64(self.body()) + "." + _b64(self.signature)

    @classmethod
    def decode(cls, text: str) -> SignerCertificate:
        body_b64, _, sig_b64 = text.partition(".")
        data = json.loads(_unb64(body_b64))
        return cls(
            data["kid"],
            data["pub"].encode(),
            data["id"],
            int(data["nbf"]),
            int(data["exp"]),
            data["root"],
            _unb64(sig_b64),
        )


class Signer:
    """An instance's ephemeral ES256 key, re-certified by the trust root every `CERT_TTL` seconds."""

    def __init__(
        self,
        root: TrustRoot,
        identity: str,
        *,
        cert_ttl: int = CERT_TTL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._identity = identity
        self._ttl = cert_ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._key: ec.EllipticCurvePrivateKey | None = None
        self._cert: SignerCertificate | None = None
        self.certifications = 0

    def current(self) -> tuple[ec.EllipticCurvePrivateKey, SignerCertificate]:
        now = int(self._clock())
        with self._lock:
            if self._cert is None or self._key is None or self._cert.exp - 120 <= now:
                key = ec.generate_private_key(ec.SECP256R1())
                pub = key.public_key().public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                )
                unsigned = SignerCertificate(
                    secrets.token_hex(8),
                    pub,
                    self._identity,
                    now - CLOCK_SKEW,
                    now + self._ttl,
                    self._root.key_id,
                    b"",
                )
                cert = SignerCertificate(
                    **{**unsigned.__dict__, "signature": self._root.sign(unsigned.body())}
                )
                self._key, self._cert = key, cert
                self.certifications += 1
            return self._key, self._cert


@dataclass(frozen=True)
class ContextClaims:
    sub: str
    org_id: str
    workspace_id: str | None
    role: str
    auth_strength: str
    scope_hash: str
    scope_version: int
    pv: int
    request_id: str
    aud: str
    jti: str
    iat: int
    exp: int
    extra: Mapping[str, Any] = field(default_factory=dict)


class ContextMinter:
    def __init__(
        self, signer: Signer, *, ttl: int = TOKEN_TTL, clock: Callable[[], float] = time.time
    ) -> None:
        self._signer = signer
        self._ttl = ttl
        self._clock = clock

    def mint(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        *,
        audience: str,
        sub: str,
        org_id: str,
        workspace_id: str | None,
        role: str,
        auth_strength: str,
        scope_hash: str,
        scope_version: int,
        pv: int,
        request_id: str,
        extra: Mapping[str, Any] | None = None,
    ) -> str:
        if audience not in SERVICES:
            raise ValueError(f"unknown audience {audience}")
        key, cert = self._signer.current()
        now = int(self._clock())
        claims = {
            "iss": ISSUER,
            "aud": audience,
            "sub": sub,
            "org_id": org_id,
            "workspace_id": workspace_id,
            "role": role,
            "auth_strength": auth_strength,
            "scope_hash": scope_hash,
            "scope_version": scope_version,
            "pv": pv,
            "request_id": request_id,
            "jti": secrets.token_urlsafe(16),
            "iat": now,
            "nbf": now - CLOCK_SKEW,
            "exp": now + self._ttl,
            **(extra or {}),
        }
        return jwt.encode(
            claims, key, algorithm="ES256", headers={"kid": cert.kid, "x5c_lmqa": cert.encode()}
        )


class ReplayCache:
    """jti reuse detection for state-changing calls; entries live until the token's expiry. Single process; the
    services that need cross-replica replay protection back it with Valkey (`SETNX ctx:jti:<jti>`)."""

    def __init__(self, max_entries: int = 200_000) -> None:
        self._seen: OrderedDict[str, int] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def first_use(self, jti: str, exp: int, now: int) -> bool:
        with self._lock:
            while self._seen and next(iter(self._seen.values())) < now:
                self._seen.popitem(last=False)
            if jti in self._seen:
                return False
            self._seen[jti] = exp
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)
            return True


class ContextVerifier:
    """Used by every internal service. Accepts only tokens for `audience`, from a certificate the trust root
    signed for the gateway identity, inside both validity windows, not on the deny list."""

    def __init__(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        audience: str,
        trust_bundle: Iterable[tuple[str, bytes]],
        *,
        issuer_identity: str = "gateway",
        replay: ReplayCache | None = None,
        clock: Callable[[], float] = time.time,
        on_foreign_identity: Callable[[str], None] | None = None,
    ) -> None:
        self._aud = audience
        self._roots = {kid: serialization.load_pem_public_key(pem) for kid, pem in trust_bundle}
        self._identity = issuer_identity
        self._replay = replay or ReplayCache()
        self._clock = clock
        self._denied: set[str] = set()
        self._alert = on_foreign_identity
        self._certs: dict[str, tuple[SignerCertificate, Any]] = {}

    def deny(self, kid: str) -> None:
        self._denied.add(kid)
        self._certs.pop(kid, None)

    def _certificate(self, header: Mapping[str, Any], now: int) -> Any:
        kid = str(header.get("kid", ""))
        if kid in self._denied:
            raise ContextTokenError("certificate revoked")
        if kid in self._certs:
            cert, key = self._certs[kid]
        else:
            try:
                cert = SignerCertificate.decode(str(header.get("x5c_lmqa", "")))
            except (
                ValueError,
                KeyError,
                TypeError,
            ) as exc:  # binascii.Error and JSONDecodeError are ValueErrors
                raise ContextTokenError("certificate malformed") from exc
            root = self._roots.get(cert.root_kid)
            if root is None or cert.kid != kid:
                raise ContextTokenError("unknown trust root")
            try:
                root.verify(cert.signature, cert.body(), ec.ECDSA(hashes.SHA256()))
            except InvalidSignature as exc:
                raise ContextTokenError("certificate signature") from exc
            key = serialization.load_pem_public_key(cert.public_pem)
            self._certs[kid] = (cert, key)
        if cert.identity != self._identity:
            if self._alert:
                self._alert(cert.identity)
            raise ContextTokenError("certificate identity")
        if not cert.nbf <= now <= cert.exp:
            raise ContextTokenError("certificate expired")
        return key

    def verify(
        self, token: str, *, state_changing: bool = False, expected_pv: int | None = None
    ) -> ContextClaims:
        now = int(self._clock())
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise ContextTokenError("malformed") from exc
        if header.get("alg") != "ES256":
            raise ContextTokenError("algorithm")
        key = self._certificate(header, now)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["ES256"],
                audience=self._aud,
                issuer=ISSUER,
                leeway=CLOCK_SKEW,
                options={"require": ["exp", "iat", "aud", "iss", "jti", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise ContextTokenError(type(exc).__name__) from exc
        if int(claims["exp"]) - int(claims["iat"]) > TOKEN_TTL + CLOCK_SKEW:
            raise ContextTokenError("lifetime")
        if state_changing and not self._replay.first_use(
            str(claims["jti"]), int(claims["exp"]), now
        ):
            raise ContextTokenError("replay")
        if expected_pv is not None and int(claims["pv"]) != expected_pv:
            raise ContextTokenError("principal version")
        known = {
            "iss",
            "aud",
            "sub",
            "org_id",
            "workspace_id",
            "role",
            "auth_strength",
            "scope_hash",
            "scope_version",
            "pv",
            "request_id",
            "jti",
            "iat",
            "nbf",
            "exp",
        }
        return ContextClaims(
            sub=str(claims["sub"]),
            org_id=str(claims["org_id"]),
            workspace_id=claims.get("workspace_id"),
            role=str(claims["role"]),
            auth_strength=str(claims["auth_strength"]),
            scope_hash=str(claims["scope_hash"]),
            scope_version=int(claims["scope_version"]),
            pv=int(claims["pv"]),
            request_id=str(claims["request_id"]),
            aud=str(claims["aud"]),
            jti=str(claims["jti"]),
            iat=int(claims["iat"]),
            exp=int(claims["exp"]),
            extra={k: v for k, v in claims.items() if k not in known},
        )


# --- signed job envelope (9.3) ---------------------------------------------------------------------------------


def sign_envelope(
    signer: Signer, payload: Mapping[str, Any], *, ttl: int = 24 * 3600
) -> dict[str, Any]:
    key, cert = signer.current()
    body = {**payload, "exp": int(time.time()) + ttl}
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
    return {
        "body": body,
        "kid": cert.kid,
        "cert": cert.encode(),
        "sig": _b64(key.sign(data, ec.ECDSA(hashes.SHA256()))),
    }


def verify_envelope(
    envelope: Mapping[str, Any],
    trust_bundle: Iterable[tuple[str, bytes]],
    *,
    identities: Iterable[str],
    now: float | None = None,
) -> dict[str, Any]:
    now_i = int(now or time.time())
    roots = {kid: serialization.load_pem_public_key(pem) for kid, pem in trust_bundle}
    try:
        cert = SignerCertificate.decode(str(envelope["cert"]))
        roots[cert.root_kid].verify(cert.signature, cert.body(), ec.ECDSA(hashes.SHA256()))
        if cert.identity not in set(identities):
            raise ContextTokenError("envelope signer identity")
        body = dict(envelope["body"])
        data = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
        serialization.load_pem_public_key(cert.public_pem).verify(
            _unb64(str(envelope["sig"])), data, ec.ECDSA(hashes.SHA256())
        )
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise ContextTokenError("envelope signature") from exc
    if int(body.get("exp", 0)) < now_i:
        raise ContextTokenError("envelope expired")
    # The certificate may have expired since signing (jobs wait in queues); the envelope's own expiry governs.
    return body


def request_digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
