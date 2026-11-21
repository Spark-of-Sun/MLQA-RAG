"""Gateway entrypoint: ``uvicorn gateway.main:app``.

The only service exposed beyond the private network.

Needs: PG_DSN_GATEWAY (reads ``principal_v`` only), VALKEY_URL, the trust root (to sign context
tokens and to verify validator verdicts), the Auth0 settings, the internal service URLs and
GATEWAY_RESUME_KEY (32 bytes as 64 hex characters). It holds no storage, vector or decryption
credentials.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from gateway.app import GatewayComponents, create_app
from gateway.limits import Idempotency, RateLimiter
from gateway.matrix import Matrix
from gateway.principal import PrincipalResolver
from gateway.query import QueryDeps
from gateway.resume import ResumeBuffer
from lmqa_audit import AuditWriter
from lmqa_auth import Auth0Settings, ContextSigner, TokenVerifier
from lmqa_auth.runtime import context_verifier, database, env, trust_root, valkey_client

_CONTRACTS = Path(env("CONTRACTS_DIR", "contracts"))


def _ws(url: str) -> str:
    return url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)


def build() -> GatewayComponents:
    """Construct the Gateway from the environment."""
    valkey, db = valkey_client("GATEWAY"), database("GATEWAY")
    namespace, client_id, domain = (
        env("AUTH0_CLAIMS_NAMESPACE"),
        env("AUTH0_CLIENT_ID_BFF"),
        env("AUTH0_DOMAIN"),
    )
    main = Auth0Settings(domain, env("AUTH0_AUDIENCE_MAIN"), frozenset({client_id}), namespace)
    onboarding = Auth0Settings(
        domain,
        env("AUTH0_AUDIENCE_ONBOARDING"),
        frozenset({client_id}),
        namespace,
        require_org=False,
    )
    services = {
        "identity": env("IDENTITY_URL"),
        "ingestion": env("INGESTION_URL"),
        "audit": env("AUDIT_URL"),
    }
    http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
    signer = ContextSigner(trust_root(), env("HOSTNAME", "gateway"))
    principals = PrincipalResolver(db, valkey)
    validator = env("VALIDATOR_URL")
    query = QueryDeps(
        signer,
        context_verifier("gateway", valkey),
        db,
        AuditWriter(),
        http,
        principals,
        ResumeBuffer(valkey, bytes.fromhex(env("GATEWAY_RESUME_KEY"))),
        env("RETRIEVAL_URL"),
        env("GENERATION_URL"),
        validator,
        _ws(validator) + "/internal/v1/validate-stream",
    )
    return GatewayComponents(
        Matrix.load(_CONTRACTS / "authz-matrix.yaml", _CONTRACTS / "features.toml"),
        TokenVerifier(main),
        TokenVerifier(onboarding),
        principals,
        RateLimiter(valkey, int(env("RATE_LIMIT_PER_MINUTE", "240"))),
        Idempotency(valkey),
        signer,
        http,
        query,
        services,
        trust_cloudflare=env("TRUST_CLOUDFLARE", "true") == "true",
    )


app = create_app(build())
