"""G3.3 context tokens and G3.5 signer certificates, against a real OpenBao trust root and Valkey."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import statistics
import time
import uuid
from typing import TYPE_CHECKING

import jwt
import pytest
import pytest_asyncio
from valkey.asyncio import Valkey

from lmqa_auth import (
    ContextClaims,
    ContextSigner,
    ContextTokenError,
    ContextVerifier,
    ValkeyDenyList,
    ValkeyJtiStore,
)
from lmqa_keys import OpenBaoTrustRoot

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage3]
SERVICES = (
    "identity",
    "ingestion",
    "retrieval",
    "generation",
    "citation_validator",
    "audit",
    "ops",
)


def _claims(role: str = "admin") -> ContextClaims:
    return ContextClaims(
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        role=role,
        auth_strength="passkey",
        scope_hash="abc",
        scope_version=3,
        principal_version=7,
        request_id=uuid.uuid4(),
        jti="",
        audience="",
        issued_at=0,
    )


@pytest_asyncio.fixture
async def valkey() -> AsyncGenerator[Valkey]:
    client = Valkey.from_url(os.environ.get("VALKEY_URL", "redis://127.0.0.1:6379"))
    yield client
    await client.aclose()


_OPEN_ROOTS: list[OpenBaoTrustRoot] = []


@pytest_asyncio.fixture(autouse=True)
async def _close_roots() -> AsyncGenerator[None]:
    """Close every trust-root HTTP client a test opened (strict warnings catch a leak)."""
    yield
    while _OPEN_ROOTS:
        await _OPEN_ROOTS.pop().aclose()


async def _root(name: str | None = None) -> OpenBaoTrustRoot:
    root = OpenBaoTrustRoot(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
        name or f"trust-root-{uuid.uuid4().hex[:8]}",
    )
    await root.create()
    _OPEN_ROOTS.append(root)
    return root


async def _verifier(
    root: OpenBaoTrustRoot, valkey: Valkey, service: str, skew: int = 5
) -> ContextVerifier:
    return ContextVerifier(
        [await root.public_key_pem()],
        service=service,
        deny_list=ValkeyDenyList(valkey),
        jti_store=ValkeyJtiStore(valkey),
        skew_seconds=skew,
    )


@pytest.mark.asyncio
async def test_a_minted_token_verifies_and_carries_the_principal(valkey: Valkey) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1")
    claims = _claims()
    token = await signer.mint(audience="retrieval", claims=claims)
    got = await (await _verifier(root, valkey, "retrieval")).verify(token)
    assert (got.user_id, got.org_id, got.workspace_id, got.role) == (
        claims.user_id,
        claims.org_id,
        claims.workspace_id,
        "admin",
    )
    assert (got.scope_hash, got.scope_version, got.principal_version) == ("abc", 3, 7)
    ctx = got.db_context()
    assert (ctx.role.value, ctx.org_id, ctx.workspace_id, ctx.user_id) == (
        "admin",
        claims.org_id,
        claims.workspace_id,
        claims.user_id,
    )


@pytest.mark.asyncio
async def test_g3_3_a_token_for_one_service_is_rejected_by_every_other_service(
    valkey: Valkey,
) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1")
    verifiers = {s: await _verifier(root, valkey, s) for s in SERVICES}
    for target in SERVICES:
        token = await signer.mint(audience=target, claims=_claims())
        for service, verifier in verifiers.items():
            if service == target:
                await verifier.verify(token)
            else:
                with pytest.raises(ContextTokenError):
                    await verifier.verify(token)


@pytest.mark.asyncio
async def test_g3_3_a_reused_token_id_is_rejected_on_state_changing_calls_only(
    valkey: Valkey,
) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1")
    verifier = await _verifier(root, valkey, "ingestion")
    token = await signer.mint(audience="ingestion", claims=_claims())
    await verifier.verify(token)  # a read may be repeated
    await verifier.verify(token)
    write = await signer.mint(audience="ingestion", claims=_claims())
    await verifier.verify(write, state_changing=True)
    with pytest.raises(ContextTokenError, match="already used"):
        await verifier.verify(write, state_changing=True)
    # Replay is detected across replicas because the record lives in shared Valkey.
    other_replica = await _verifier(root, valkey, "ingestion")
    with pytest.raises(ContextTokenError, match="already used"):
        await other_replica.verify(write, state_changing=True)


@pytest.mark.asyncio
async def test_an_expired_token_is_rejected(valkey: Valkey) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1", token_lifetime=1)
    token = await signer.mint(audience="audit", claims=_claims())
    verifier = await _verifier(root, valkey, "audit", skew=0)
    await verifier.verify(token)
    await asyncio.sleep(2.2)  # real time; lifetimes are configuration, never a faked clock
    with pytest.raises(ContextTokenError):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_tampered_claims_certificates_and_foreign_roots_are_rejected(valkey: Valkey) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1")
    verifier = await _verifier(root, valkey, "generation")
    good = await signer.mint(audience="generation", claims=_claims("tenant"))
    head, payload, sig = good.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body["role"] = "admin"  # privilege escalation attempt
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    with pytest.raises(ContextTokenError):
        await verifier.verify(f"{head}.{forged}.{sig}")
    # A certificate with a stretched validity window no longer matches the root's signature.
    header = jwt.get_unverified_header(good)
    cert_payload, cert_sig = header["cert"].split(".")
    cert = json.loads(base64.urlsafe_b64decode(cert_payload + "=="))
    cert["exp"] += 86400
    stretched = (
        base64.urlsafe_b64encode(json.dumps(cert, sort_keys=True, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    new_head = (
        base64.urlsafe_b64encode(json.dumps({**header, "cert": f"{stretched}.{cert_sig}"}).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(ContextTokenError):
        await verifier.verify(f"{new_head}.{payload}.{sig}")
    # A signer certified by a different root is not trusted.
    rogue = ContextSigner(await _root(), "rogue-pod")
    with pytest.raises(ContextTokenError, match="trusted root"):
        await verifier.verify(await rogue.mint(audience="generation", claims=_claims()))
    for bad in ("", "a.b.c", good[:-4] + "AAAA"):
        with pytest.raises(ContextTokenError):
            await verifier.verify(bad)


@pytest.mark.asyncio
async def test_g3_5_one_trust_root_call_per_instance_not_per_request() -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1")
    latencies = []
    for _ in range(2000):
        start = time.perf_counter()
        await signer.mint(audience="retrieval", claims=_claims())
        latencies.append((time.perf_counter() - start) * 1000)
    assert signer.trust_root_calls == 1, "2000 tokens, one KMS-style signature"
    p99 = statistics.quantiles(latencies, n=100)[98]
    assert p99 <= 5.0, f"minting p99 was {p99:.2f} ms (budget 5 ms)"


@pytest.mark.asyncio
async def test_g3_5_the_deny_list_revokes_a_pod_at_once_and_only_that_pod(valkey: Valkey) -> None:
    root = await _root()
    pod_a, pod_b = ContextSigner(root, "pod-a"), ContextSigner(root, "pod-b")
    verifier = await _verifier(root, valkey, "retrieval")
    token_a = await pod_a.mint(audience="retrieval", claims=_claims())
    token_b = await pod_b.mint(audience="retrieval", claims=_claims())
    await verifier.verify(token_a)
    started = time.perf_counter()
    await ValkeyDenyList(valkey).deny((await pod_a.certificate()).cert_id)
    with pytest.raises(ContextTokenError, match="revoked"):
        await verifier.verify(token_a)
    assert time.perf_counter() - started < 2.0, "revocation takes effect within 2 s"
    await verifier.verify(token_b)


@pytest.mark.asyncio
async def test_g3_5_a_stolen_signer_key_is_useless_after_its_certificate_expires(
    valkey: Valkey,
) -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1", cert_lifetime=2)
    token = await signer.mint(audience="ops", claims=_claims())
    verifier = await _verifier(root, valkey, "ops", skew=0)
    await verifier.verify(token)
    await asyncio.sleep(2.5)
    with pytest.raises(ContextTokenError, match="validity window"):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_the_signer_re_certifies_before_expiry_and_policy_caps_lifetimes() -> None:
    root = await _root()
    signer = ContextSigner(root, "gateway-pod-1", cert_lifetime=2)
    first = (await signer.certificate()).cert_id
    await asyncio.sleep(1.2)  # inside the refresh margin
    assert (await signer.certificate()).cert_id != first
    assert signer.trust_root_calls == 2
    for kwargs in (
        {"cert_lifetime": 3601},
        {"cert_lifetime": 0},
        {"token_lifetime": 61},
        {"token_lifetime": 0},
    ):
        with pytest.raises(ValueError, match="lifetime"):
            ContextSigner(root, "x", **kwargs)


@pytest.mark.asyncio
async def test_a_rotation_overlap_trusts_both_roots(valkey: Valkey) -> None:
    old, new = await _root(), await _root()
    verifier = ContextVerifier(
        [await old.public_key_pem(), await new.public_key_pem()],
        service="audit",
        deny_list=ValkeyDenyList(valkey),
        jti_store=ValkeyJtiStore(valkey),
    )
    for root in (old, new):
        await verifier.verify(
            await ContextSigner(root, "pod").mint(audience="audit", claims=_claims())
        )
