"""G3.1 token abuse. Tokens are signed locally with a real RSA key and fetched through a real
HTTP JWKS endpoint. Crafted malformed JWTs are labelled instruments (doc 19.1, R6). This does NOT
replace the live-Auth0 gates (G0.7, G2.7, G8.1), which need a real tenant."""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from lmqa_auth import Auth0Settings, TokenRejectedError, TokenVerifier

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit, pytest.mark.control, pytest.mark.stage3]

ISSUER_DOMAIN = "tenant.example.test"
AUDIENCE = "https://api.onekami.site"
CLIENT = "web-bff-client-id"
NS = "https://claims.onekami.site"


def _rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


class _Jwks:
    def __init__(self) -> None:
        self.keys: list[dict[str, Any]] = []
        self.hits = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.hits += 1
                body = json.dumps({"keys": owner.keys}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/jwks.json"


@pytest.fixture
def idp() -> Iterator[tuple[_Jwks, rsa.RSAPrivateKey]]:
    jwks, key = _Jwks(), _rsa()
    jwks.keys = [_jwk(key, "k1")]
    yield jwks, key
    jwks.server.shutdown()
    jwks.server.server_close()  # close the listening socket (strict warnings catch a leak)
    jwks.thread.join(timeout=5)


def _settings() -> Auth0Settings:
    return Auth0Settings(ISSUER_DOMAIN, AUDIENCE, frozenset({CLIENT}), NS)


def _verifier(jwks: _Jwks) -> TokenVerifier:
    from jwt import PyJWKClient  # noqa: PLC0415

    return TokenVerifier(_settings(), jwk_client=PyJWKClient(jwks.url, cache_keys=True))


def _token(key: rsa.RSAPrivateKey, kid: str = "k1", alg: str = "RS256", **over: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": f"https://{ISSUER_DOMAIN}/",
        "aud": AUDIENCE,
        "sub": "auth0|abc",
        "azp": CLIENT,
        "iat": now,
        "exp": now + 600,
        "org_id": "org_123",
        f"{NS}/auth_strength": "passkey",
        f"{NS}/role": "admin",
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def test_a_valid_token_is_accepted_and_only_the_trusted_claims_are_extracted(idp) -> None:
    jwks, key = idp
    verified = _verifier(jwks).verify(_token(key))
    assert (verified.sub, verified.org_id, verified.azp) == ("auth0|abc", "org_123", CLIENT)
    assert verified.auth_strength == "passkey"
    assert verified.advisory_role == "admin"


@pytest.mark.parametrize(
    ("label", "override"),
    [
        ("wrong audience", {"aud": "https://other.example"}),
        ("ID token used as an access token", {"aud": CLIENT, "nonce": "n"}),
        ("expired", {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}),
        ("not yet valid", {"nbf": int(time.time()) + 3600}),
        ("wrong issuer", {"iss": "https://evil.example/"}),
        ("issuer without trailing slash", {"iss": f"https://{ISSUER_DOMAIN}"}),
        ("missing org_id", {"org_id": None}),
        ("empty org_id", {"org_id": ""}),
        ("authorized party not allowed", {"azp": "someone-elses-client"}),
        ("missing azp", {"azp": None}),
        ("missing exp", {"exp": None}),
        ("missing sub", {"sub": None}),
    ],
)
def test_abusive_claims_are_rejected(idp, label: str, override: dict[str, Any]) -> None:
    jwks, key = idp
    with pytest.raises(TokenRejectedError):
        _verifier(jwks).verify(_token(key, **override))
    assert label


def test_skew_of_thirty_seconds_is_tolerated_but_not_more(idp) -> None:
    jwks, key = idp
    now = int(time.time())
    _verifier(jwks).verify(_token(key, exp=now - 20, iat=now - 600))
    with pytest.raises(TokenRejectedError):
        _verifier(jwks).verify(_token(key, exp=now - 45, iat=now - 600))


def test_alg_none_is_rejected(idp) -> None:
    jwks, _key = idp
    now = int(time.time())
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT", "kid": "k1"}).encode()
    ).rstrip(b"=")
    body = base64.urlsafe_b64encode(
        json.dumps(
            {
                "iss": f"https://{ISSUER_DOMAIN}/",
                "aud": AUDIENCE,
                "sub": "x",
                "azp": CLIENT,
                "iat": now,
                "exp": now + 600,
                "org_id": "o",
            }
        ).encode()
    ).rstrip(b"=")
    with pytest.raises(TokenRejectedError, match="algorithm"):
        _verifier(jwks).verify(f"{header.decode()}.{body.decode()}.")


def test_hs256_signed_with_the_public_key_as_the_secret_is_rejected(idp) -> None:
    """The classic algorithm-confusion attack."""
    jwks, key = idp
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    now = int(time.time())
    forged = (
        jwt.encode(
            {
                "iss": f"https://{ISSUER_DOMAIN}/",
                "aud": AUDIENCE,
                "sub": "x",
                "azp": CLIENT,
                "iat": now,
                "exp": now + 600,
                "org_id": "o",
            },
            public_pem,
            algorithm="HS256",
            headers={"kid": "k1"},
        )
        if False
        else None
    )  # PyJWT itself refuses to HMAC with a PEM key; build the token by hand
    import hashlib  # noqa: PLC0415
    import hmac  # noqa: PLC0415

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode()
    ).rstrip(b"=")
    body = base64.urlsafe_b64encode(
        json.dumps(
            {
                "iss": f"https://{ISSUER_DOMAIN}/",
                "aud": AUDIENCE,
                "sub": "x",
                "azp": CLIENT,
                "iat": now,
                "exp": now + 600,
                "org_id": "o",
            }
        ).encode()
    ).rstrip(b"=")
    signing_input = header + b"." + body
    sig = base64.urlsafe_b64encode(
        hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    assert forged is None
    with pytest.raises(TokenRejectedError, match="algorithm"):
        _verifier(jwks).verify((signing_input + b"." + sig).decode())


def test_tampered_payload_and_foreign_signatures_are_rejected(idp) -> None:
    jwks, key = idp
    good = _token(key)
    head, payload, sig = good.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["org_id"] = "org_other"
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(TokenRejectedError):
        _verifier(jwks).verify(f"{head}.{forged_payload}.{sig}")
    with pytest.raises(TokenRejectedError):  # right kid, signed by a different key
        _verifier(jwks).verify(_token(_rsa()))
    with pytest.raises(TokenRejectedError):
        _verifier(jwks).verify(good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"))


@pytest.mark.parametrize("garbage", ["", "x", "a.b", "a.b.c", "....", "Bearer abc"])
def test_garbage_is_rejected(idp, garbage: str) -> None:
    jwks, _key = idp
    with pytest.raises(TokenRejectedError):
        _verifier(jwks).verify(garbage)


def test_unknown_kid_triggers_one_rate_limited_refresh(idp) -> None:
    jwks, _key = idp
    rotated = _rsa()
    verifier = _verifier(jwks)
    with pytest.raises(TokenRejectedError):
        verifier.verify(_token(rotated, kid="k2"))  # unknown kid; keys have not rotated yet
    hits_after_first = jwks.hits
    jwks.keys = [*jwks.keys, _jwk(rotated, "k2")]  # the IdP publishes the new key
    with pytest.raises(TokenRejectedError):
        verifier.verify(_token(rotated, kid="k2"))  # refresh is rate limited to once a minute
    assert jwks.hits == hits_after_first, "no second JWKS fetch inside the minute"
