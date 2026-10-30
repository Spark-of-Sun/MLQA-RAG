"""Stage 3 on the real stack: the Gateway in front of the real identity service (tokens signed locally).

Tokens here are signed with a real RSA key and verified through a real HTTP JWKS endpoint; this does
NOT replace the live-Auth0 gates (G0.7, G2.7, G8.1). The identity service, PostgreSQL, Valkey and the
OpenBao trust root are the real ones.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import jwt
import pytest
import pytest_asyncio
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import text
from valkey.asyncio import Valkey

from citation_validator.service import signing_bytes as validator_signing_bytes
from gateway.app import GatewayComponents, create_app
from gateway.limits import Idempotency, RateLimiter
from gateway.matrix import Matrix
from gateway.principal import PrincipalResolver
from gateway.query import QueryDeps, run_query, signing_bytes
from gateway.resume import ResumeBuffer
from identity.app import create_app as create_identity_app
from identity.codes import CodeService
from identity.codes import RateLimiter as CodeLimiter
from identity.domain import Identity
from lmqa_audit import AuditWriter
from lmqa_auth import (
    Auth0Settings,
    ContextSigner,
    ContextVerifier,
    TokenVerifier,
    ValkeyDenyList,
    ValkeyJtiStore,
)
from lmqa_db import ContextRole, Database, DbContext
from lmqa_keys import KeyService, OpenBaoProvider, OpenBaoTrustRoot
from lmqa_testing import world
from lmqa_testing.fixtures import Stack
from lmqa_testing.pg import role_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage3]
ROOT = Path(__file__).resolve().parents[2]
AUDIENCE, ONBOARDING, CLIENT, NS, DOMAIN = (
    "https://api.test",
    "https://onboarding.test",
    "bff",
    "https://claims.test",
    "tenant.test",
)
OPENBAO = (
    os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
    os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
)
DEAD = "http://127.0.0.1:1"


class _Jwks:
    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        body = json.dumps(
            {
                "keys": [
                    {
                        **json.loads(RSAAlgorithm.to_jwk(key.public_key())),
                        "kid": "k1",
                        "use": "sig",
                        "alg": "RS256",
                    }
                ]
            }
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/jwks.json"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@asynccontextmanager
async def serve(app: object) -> AsyncGenerator[int]:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))  # type: ignore[arg-type]
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    try:
        yield int(sock.getsockname()[1])
    finally:
        server.should_exit = True
        await task
        sock.close()


@dataclass
class Rig:
    app: Any
    comp: GatewayComponents
    identity: Identity
    db: Database
    valkey: Valkey
    key: rsa.RSAPrivateKey
    client: httpx.AsyncClient
    stack: Stack


def make_token(
    key: rsa.RSAPrivateKey,
    sub: str,
    *,
    org: str | None = "org_main",
    audience: str = AUDIENCE,
    role: str | None = None,
    strength: str = "passkey",
    auth_age: int = 10,
    exp: int = 600,
    azp: str = CLIENT,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": f"https://{DOMAIN}/",
        "aud": audience,
        "sub": sub,
        "azp": azp,
        "iat": now - 5,
        "exp": now + exp,
        "auth_time": now - auth_age,
        f"{NS}/auth_strength": strength,
    }
    if org:
        claims["org_id"] = org
    if role:
        claims[f"{NS}/role"] = role
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@pytest_asyncio.fixture
async def rig(migrated_db: str, stack: Stack) -> AsyncGenerator[Rig]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = _Jwks(key)
    provider = OpenBaoProvider(*OPENBAO)
    valkey = Valkey.from_url(os.environ.get("VALKEY_URL", "redis://127.0.0.1:6379"))
    id_db = Database(role_dsn("svc_identity", migrated_db), pooled=False, use_null_pool=True)
    gw_db = Database(role_dsn("svc_gateway", migrated_db), pooled=False, use_null_pool=True)
    trust = OpenBaoTrustRoot(*OPENBAO, f"gw-root-{uuid.uuid4().hex[:8]}")
    await trust.create()
    pub = [await trust.public_key_pem()]
    deny, jti = ValkeyDenyList(valkey), ValkeyJtiStore(valkey)
    identity = Identity(
        id_db,
        KeyService(provider),
        provider,
        CodeService(id_db, CodeLimiter(valkey), {"v1": secrets.token_bytes(32)}, "v1"),
        valkey,
    )
    id_app = create_identity_app(
        identity, ContextVerifier(pub, service="identity", deny_list=deny, jti_store=jti)
    )
    signer = ContextSigner(trust, "gateway-pod")
    http = httpx.AsyncClient(timeout=20)
    principals = PrincipalResolver(gw_db, valkey)
    async with serve(id_app) as port:
        main = Auth0Settings(DOMAIN, AUDIENCE, frozenset({CLIENT}), NS)
        onboarding = Auth0Settings(DOMAIN, ONBOARDING, frozenset({CLIENT}), NS, require_org=False)
        query = QueryDeps(
            signer,
            ContextVerifier(pub, service="gateway", deny_list=deny, jti_store=jti),
            gw_db,
            AuditWriter(),
            http,
            principals,
            ResumeBuffer(valkey, secrets.token_bytes(32)),
            DEAD,
            DEAD,
            DEAD,
            "ws://127.0.0.1:1",
        )
        comp = GatewayComponents(
            Matrix.load(ROOT / "contracts/authz-matrix.yaml", ROOT / "contracts/features.toml"),
            TokenVerifier(main, jwk_client=PyJWKClient(jwks.url)),
            TokenVerifier(onboarding, jwk_client=PyJWKClient(jwks.url)),
            principals,
            RateLimiter(valkey, per_minute=1000),
            Idempotency(valkey),
            signer,
            http,
            query,
            {"identity": f"http://127.0.0.1:{port}", "ingestion": DEAD, "audit": DEAD},
            trust_cloudflare=False,
        )
        app = create_app(comp)
        listener = asyncio.create_task(principals.listen())
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway", timeout=20
        )
        yield Rig(app, comp, identity, id_db, valkey, key, client, stack)
        listener.cancel()
        await client.aclose()
    await http.aclose()
    for d in (id_db, gw_db):
        await d.dispose()
    await trust.aclose()
    await valkey.aclose()
    await provider.aclose()
    jwks.close()


async def org_with_admin(rig: Rig) -> tuple[str, str, DbContext, UUID, str]:
    """An organization (Super Admin sub, Auth0 org id) with an approved admin."""
    sa_sub, auth0_org = f"auth0|{uuid.uuid4().hex}", f"org_{uuid.uuid4().hex[:10]}"
    created = await rig.identity.create_organization(sa_sub, "Acme LLP", "both")
    org = UUID(created["organization_id"])
    async with rig.db.scoped(world.SYSTEM) as s:
        await s.execute(
            text("UPDATE orgs SET auth0_org_id = :a WHERE id = :o"), {"a": auth0_org, "o": org}
        )
        sa = UUID(
            str(
                (
                    await s.execute(
                        text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": sa_sub}
                    )
                ).scalar_one()
            )
        )
    sa_ctx = DbContext(role=ContextRole.SUPER_ADMIN, org_id=org, user_id=sa)
    admin_sub = f"auth0|{uuid.uuid4().hex}"
    await rig.identity.join_admin(
        admin_sub, await rig.identity.generate_org_code(sa_ctx), "10.0.0.1"
    )
    async with rig.db.scoped(world.SYSTEM) as s:
        admin = UUID(
            str(
                (
                    await s.execute(
                        text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": admin_sub}
                    )
                ).scalar_one()
            )
        )
    await rig.identity.decide_admin(sa_ctx, admin, "approve")
    return sa_sub, auth0_org, sa_ctx, admin, admin_sub


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_every_authentication_failure_gets_the_identical_401(rig: Rig) -> None:
    sa_sub, auth0_org, _ctx, _admin, _asub = await org_with_admin(rig)
    k, other = rig.key, rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = {
        "no header": {},
        "junk": bearer("not.a.token"),
        "wrong signature": bearer(make_token(other, sa_sub, org=auth0_org)),
        "wrong audience": bearer(make_token(k, sa_sub, org=auth0_org, audience="https://other")),
        "expired": bearer(make_token(k, sa_sub, org=auth0_org, exp=-120)),
        "foreign org": bearer(make_token(k, sa_sub, org="org_somebody_else")),
        "unknown user": bearer(make_token(k, "auth0|nobody", org=auth0_org)),
        "wrong client": bearer(make_token(k, sa_sub, org=auth0_org, azp="evil")),
        "onboarding token on the main API": bearer(
            make_token(k, sa_sub, org=None, audience=ONBOARDING)
        ),
    }
    bodies = set()
    for label, headers in bad.items():
        r = await rig.client.get("/v1/me", headers=headers)
        assert r.status_code == 401, label
        bodies.add(r.text)
    assert len(bodies) == 1, "one body whatever went wrong"
    ok = await rig.client.get("/v1/me", headers=bearer(make_token(k, sa_sub, org=auth0_org)))
    assert ok.status_code == 200
    assert ok.json()["role"] == "super_admin"


@pytest.mark.asyncio
async def test_g3_6_each_role_reaches_only_its_routes_and_a_forbidden_route_is_404_not_403(
    rig: Rig,
) -> None:
    sa_sub, auth0_org, sa_ctx, _admin, admin_sub = await org_with_admin(rig)
    tenant_sub = f"auth0|{uuid.uuid4().hex}"
    async with rig.db.scoped(world.SYSTEM) as s:
        ws = (
            await s.execute(
                text("SELECT workspace_id FROM memberships WHERE role = 'admin' AND org_id = :o"),
                {"o": sa_ctx.org},
            )
        ).scalar_one()
    admin_ctx = DbContext(
        role=ContextRole.ADMIN, org_id=sa_ctx.org, workspace_id=ws, user_id=_admin
    )
    await rig.identity.join_tenant(
        tenant_sub, await rig.identity.generate_admin_code(admin_ctx), "10.0.0.2"
    )
    async with rig.db.scoped(world.SYSTEM) as s:
        tenant = UUID(
            str(
                (
                    await s.execute(
                        text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": tenant_sub}
                    )
                ).scalar_one()
            )
        )
    await rig.identity.decide_tenant(admin_ctx, tenant, "approve")
    tok = {
        r: bearer(make_token(rig.key, s, org=auth0_org))
        for r, s in (("SA", sa_sub), ("AD", admin_sub), ("TE", tenant_sub))
    }
    expect = {  # (method, path): roles that get through to the service
        ("GET", "/v1/org/admins"): {"SA"},
        ("GET", "/v1/workspace/tenants"): {"AD"},
        ("GET", "/v1/workspace/walls"): {"AD"},
        ("GET", "/v1/workspace/matters"): {"AD", "TE"},
        ("GET", "/v1/me"): {"SA", "AD", "TE"},
    }
    for (method, path), allowed in expect.items():
        for role, headers in tok.items():
            r = await rig.client.request(method, path, headers=headers)
            if role in allowed:
                assert r.status_code == 200, (role, path, r.status_code)
            else:
                assert r.status_code == 404, (
                    role,
                    path,
                    "a role that may not call a route must see 404, not 403",
                )
    for role, headers in tok.items():  # a Super Admin has no route to documents or queries, ever
        for path in ("/v1/documents", "/v1/workspace/tenants"):
            assert (await rig.client.get(path, headers=headers)).status_code in (
                {404} if role == "SA" else {200, 404, 502}
            )
    deferred = await rig.client.post("/v1/governance-requests", headers=tok["SA"], json={})
    assert deferred.status_code == 404, "a disabled feature answers as if it did not exist"
    assert not any(
        r.status_code == 403 for r in [await rig.client.get("/v1/org/admins", headers=tok["TE"])]
    )


@pytest.mark.asyncio
async def test_roles_come_from_the_database_and_an_advisory_claim_mismatch_is_refused(
    rig: Rig,
) -> None:
    _sa_sub, auth0_org, _ctx, _admin, admin_sub = await org_with_admin(rig)
    honest = await rig.client.get(
        "/v1/me", headers=bearer(make_token(rig.key, admin_sub, org=auth0_org, role="admin"))
    )
    assert honest.status_code == 200
    liar = await rig.client.get(
        "/v1/me", headers=bearer(make_token(rig.key, admin_sub, org=auth0_org, role="super_admin"))
    )
    assert liar.status_code == 401, (
        "a token claiming a higher role than the database says is refused"
    )


@pytest.mark.asyncio
async def test_g3_4_suspension_reaches_the_gateway_within_two_seconds_and_blocks_new_requests(
    rig: Rig,
) -> None:
    _sa_sub, auth0_org, sa_ctx, admin, admin_sub = await org_with_admin(rig)
    headers = bearer(make_token(rig.key, admin_sub, org=auth0_org))
    assert (
        await rig.client.get("/v1/me", headers=headers)
    ).status_code == 200  # warms the 5 s local cache
    await asyncio.sleep(0.3)  # let the listener subscribe
    started = time.perf_counter()
    await rig.identity.decide_admin(sa_ctx, admin, "suspend")
    for _ in range(40):
        if (await rig.client.get("/v1/me", headers=headers)).status_code == 401:
            break
        await asyncio.sleep(0.05)
    elapsed = time.perf_counter() - started
    assert (await rig.client.get("/v1/me", headers=headers)).status_code == 401
    assert elapsed < 2.0, f"revocation took {elapsed:.2f} s (target p99 <= 2 s)"
    assert rig.comp.principals.revocations_seen >= 1


@pytest.mark.asyncio
async def test_a_pending_member_may_only_read_their_own_status(rig: Rig) -> None:
    _sa_sub, auth0_org, sa_ctx, _admin, _asub = await org_with_admin(rig)
    pending = f"auth0|{uuid.uuid4().hex}"
    await rig.identity.join_admin(pending, await rig.identity.generate_org_code(sa_ctx), "10.0.0.9")
    headers = bearer(make_token(rig.key, pending, org=auth0_org))
    assert (await rig.client.get("/v1/me", headers=headers)).status_code == 200
    for path in ("/v1/org/admins", "/v1/workspace/tenants", "/v1/documents"):
        assert (await rig.client.get(path, headers=headers)).status_code in {401, 404}, path


@pytest.mark.asyncio
async def test_g3_8_step_up_returns_the_rfc_9470_challenge_and_a_fresh_strong_login_passes(
    rig: Rig,
) -> None:
    sa_sub, auth0_org, *_ = await org_with_admin(rig)
    stale = await rig.client.post(
        "/v1/org/code", headers=bearer(make_token(rig.key, sa_sub, org=auth0_org, auth_age=3600))
    )
    assert stale.status_code == 401
    challenge = stale.headers["www-authenticate"]
    assert 'error="insufficient_user_authentication"' in challenge
    assert "max_age=300" in challenge
    weak = await rig.client.post(
        "/v1/org/code",
        headers=bearer(make_token(rig.key, sa_sub, org=auth0_org, strength="otp_mfa")),
    )
    assert weak.status_code == 401
    assert "insufficient_user_authentication" in weak.headers["www-authenticate"]
    assert (
        await rig.client.get(
            "/v1/me",
            headers=bearer(make_token(rig.key, sa_sub, org=auth0_org, strength="password")),
        )
    ).status_code == 200
    assert (
        await rig.client.get(
            "/v1/org/admins",
            headers=bearer(make_token(rig.key, sa_sub, org=auth0_org, strength="otp_mfa")),
        )
    ).status_code == 401
    fresh = await rig.client.post(
        "/v1/org/code", headers=bearer(make_token(rig.key, sa_sub, org=auth0_org, auth_age=5))
    )
    assert fresh.status_code == 201
    assert len(fresh.json()["code"].replace("-", "")) == 64


@pytest.mark.asyncio
async def test_g3_9_a_replayed_idempotency_key_applies_once_and_a_different_request_is_refused(
    rig: Rig,
) -> None:
    _sa_sub, auth0_org, _ctx, _admin, admin_sub = await org_with_admin(rig)
    headers = {
        **bearer(make_token(rig.key, admin_sub, org=auth0_org)),
        "Idempotency-Key": uuid.uuid4().hex,
    }
    first = await rig.client.post(
        "/v1/workspace/matters", headers=headers, json={"label": "Smith v. Jones"}
    )
    second = await rig.client.post(
        "/v1/workspace/matters", headers=headers, json={"label": "Smith v. Jones"}
    )
    assert first.status_code == second.status_code == 201
    assert second.headers.get("idempotent-replay") == "true"
    assert second.json() == first.json(), "the original response is returned"
    listing = await rig.client.get(
        "/v1/workspace/matters", headers=bearer(make_token(rig.key, admin_sub, org=auth0_org))
    )
    assert [m["label"] for m in listing.json()["matters"]] == ["Smith v. Jones"], (
        "applied exactly once"
    )
    clash = await rig.client.post(
        "/v1/workspace/matters", headers=headers, json={"label": "A different request"}
    )
    assert clash.status_code == 422


@pytest.mark.asyncio
async def test_g3_9_limits_hold_and_a_dead_valkey_degrades_to_a_conservative_local_limit(
    rig: Rig,
) -> None:
    user = uuid.uuid4()
    tight = RateLimiter(rig.valkey, per_minute=3)
    assert [await tight.allow(user) for _ in range(5)] == [True, True, True, False, False]
    dead = RateLimiter(Valkey.from_url("redis://127.0.0.1:1"), per_minute=1000)
    results = [await dead.allow(uuid.UUID(int=7)) for _ in range(40)]
    assert results[:30] == [True] * 30, "Valkey down: the first requests are allowed"
    assert results[30:] == [False] * 10, "Valkey down: limited, not unlimited"


@pytest.mark.asyncio
async def test_onboarding_uses_its_own_audience_and_an_org_scoped_token_is_refused_there(
    rig: Rig,
) -> None:
    sub = f"auth0|{uuid.uuid4().hex}"
    token = make_token(rig.key, sub, org=None, audience=ONBOARDING)
    created = await rig.client.post(
        "/v1/onboarding/organization",
        headers=bearer(token),
        json={"name": "Brand New Firm", "deployment_type": "legal"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["created"] is True
    status = await rig.client.get("/v1/onboarding/status", headers=bearer(token))
    assert status.json() == {
        "member": True,
        "role": "super_admin",
        "state": "active",
        "reason": None,
        "auth0_org_id": None,  # the dev organization is not mirrored to Auth0 in this test
    }
    scoped = make_token(rig.key, sub, org="org_main", audience=ONBOARDING)
    assert (
        await rig.client.get("/v1/onboarding/status", headers=bearer(scoped))
    ).status_code == 401
    assert (await rig.client.get("/v1/org/admins", headers=bearer(token))).status_code == 401, (
        "no org claim: not the main API"
    )
    bad_code = await rig.client.post(
        "/v1/onboarding/join-tenant",
        headers=bearer(
            make_token(rig.key, f"auth0|{uuid.uuid4().hex}", org=None, audience=ONBOARDING)
        ),
        json={"code": "not-a-code"},
    )
    assert bad_code.status_code == 400
    assert bad_code.json()["title"] == "Code invalid or expired"


def test_the_gateway_and_validator_agree_byte_for_byte_on_what_is_signed() -> None:
    payload = {
        "v": 1,
        "request_id": str(uuid.uuid4()),
        "index": 3,
        "sentence": "Fee is $5 [chunk_1].",
        "passed": True,
        "aliases": ["chunk_1"],
    }
    assert signing_bytes(payload) == validator_signing_bytes(payload)


@pytest.mark.asyncio
async def test_the_resume_buffer_replays_only_to_the_same_user_and_stores_ciphertext(
    rig: Rig,
) -> None:
    buf = ResumeBuffer(rig.valkey, secrets.token_bytes(32))
    request, owner, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for n in (1, 2, 3):
        await buf.append(
            request, owner, n, f"event: sentence\ndata: secret clause {n}\n\n".encode()
        )
    assert [
        f.decode().split("secret clause ")[1][0] for f in await buf.after(request, owner, 1)
    ] == ["2", "3"]
    assert await buf.after(request, other, 0) == [], "another user gets nothing"
    raw = b"".join(bytes(x) for x in await rig.valkey.lrange(f"resume:{request}", 0, -1))
    assert b"secret clause" not in raw


@pytest.mark.asyncio
async def test_the_audit_record_is_written_before_anything_else_and_a_failing_audit_stops_the_stream(
    rig: Rig,
) -> None:
    _sa, auth0_org, _ctx, admin, admin_sub = await org_with_admin(rig)
    principal = await rig.comp.principals.resolve(admin_sub, auth0_org)
    assert principal is not None
    ctx = DbContext(
        role=ContextRole.ADMIN,
        org_id=principal.org_id,
        workspace_id=principal.workspace_id,
        user_id=admin,
    )
    events = [
        chunk
        async for chunk in run_query(rig.comp.query, principal, ctx, "What is the notice period?")
    ]
    text_out = b"".join(events).decode()
    assert "event: status" in text_out
    assert "event: error" in text_out, "retrieval is down: a clear error, no answer"
    assert "upstream_unavailable" in text_out
    assert "event: sentence" not in text_out
    async with rig.stack.audit_reader.scoped(ctx) as s:
        actions = [
            r[0]
            for r in (await s.execute(text("SELECT action FROM audit_event ORDER BY seq"))).all()
        ]
    assert "query.started" in actions, "the write-ahead record exists even though the query failed"
    dead_db = Database(
        "postgresql://svc_gateway@127.0.0.1:1/none", pooled=False, use_null_pool=True
    )
    broken = QueryDeps(
        rig.comp.query.signer,
        rig.comp.query.verifier,
        dead_db,
        rig.comp.query.audit,
        rig.comp.query.http,
        rig.comp.query.resolver,
        rig.comp.query.resume,
        DEAD,
        DEAD,
        DEAD,
        "ws://127.0.0.1:1",
    )
    stopped = b"".join(
        [chunk async for chunk in run_query(broken, principal, ctx, "Another question")]
    ).decode()
    await dead_db.dispose()
    assert "audit_unavailable" in stopped, "if the audit write fails the stream stops"
    assert "event: status" not in stopped, "...before anything is retrieved or released"


@pytest.mark.asyncio
async def test_request_bodies_with_uuid_and_datetime_fields_work_through_the_gateway(
    rig: Rig,
) -> None:
    """Regression: a lint autofix once moved UUID/datetime imports under TYPE_CHECKING, which breaks both
    Pydantic request models and FastAPI path parameters. Unit tests never parsed these bodies; HTTP does."""
    sa_sub, auth0_org, sa_ctx, admin, admin_sub = await org_with_admin(rig)
    async with rig.db.scoped(world.SYSTEM) as s:
        ws = (
            await s.execute(
                text("SELECT workspace_id FROM memberships WHERE role = 'admin' AND org_id = :o"),
                {"o": sa_ctx.org},
            )
        ).scalar_one()
    admin_ctx = DbContext(role=ContextRole.ADMIN, org_id=sa_ctx.org, workspace_id=ws, user_id=admin)
    tenant_sub = f"auth0|{uuid.uuid4().hex}"
    await rig.identity.join_tenant(
        tenant_sub, await rig.identity.generate_admin_code(admin_ctx), "10.0.0.7"
    )
    async with rig.db.scoped(world.SYSTEM) as s:
        tenant = UUID(
            str(
                (
                    await s.execute(
                        text("SELECT id FROM users WHERE auth0_sub = :s"), {"s": tenant_sub}
                    )
                ).scalar_one()
            )
        )
    headers = bearer(make_token(rig.key, admin_sub, org=auth0_org))
    matter = (
        await rig.client.post(
            "/v1/workspace/matters", headers=headers, json={"label": "Acme v. Beta"}
        )
    ).json()["id"]
    expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    approved = await rig.client.post(
        f"/v1/workspace/tenants/{tenant}/approve",
        headers=headers,
        json={"grants": [{"matter_id": matter, "max_tier": 2, "expires_at": expires}]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json() == {"state": "active"}
    put = await rig.client.put(
        f"/v1/workspace/tenants/{tenant}/grants",
        headers=headers,
        json=[{"matter_id": matter, "max_tier": 3}],
    )
    assert put.status_code == 204, put.text
    async with rig.db.scoped(admin_ctx) as s:
        row = (
            await s.execute(
                text("SELECT max_tier, expires_at FROM matter_grants WHERE user_id = :u"),
                {"u": tenant},
            )
        ).one()
    assert (row[0], row[1]) == (3, None), "the replaced grant has the new ceiling and no expiry"
    bad = await rig.client.put(
        f"/v1/workspace/tenants/{tenant}/grants",
        headers=headers,
        json=[{"matter_id": "not-a-uuid", "max_tier": 9}],
    )
    assert bad.status_code == 422, (
        "a malformed UUID and an out-of-range tier are refused, not coerced"
    )
    unknown = await rig.client.post(f"/v1/workspace/tenants/{tenant}/delete", headers=headers)
    assert unknown.status_code == 404, (
        "an action that is not one of the four explicit routes does not exist"
    )
    suspended = await rig.client.post(
        f"/v1/org/admins/{admin}/suspend",
        headers=bearer(make_token(rig.key, sa_sub, org=auth0_org)),
    )
    assert suspended.status_code == 200, suspended.text
