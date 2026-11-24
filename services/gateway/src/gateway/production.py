"""Production routes and trust wiring (blueprint 5.5 to 5.8, 6.7, 8.5, 8.6, 9, 11.6, 15).

Every route here is listed in contracts/authz-matrix.yaml with the feature flag that gates it; while a feature is
disabled (contracts/features.toml) its routes answer 404, exactly like a route that does not exist (18). Routes with
`step_up: true` require a passkey authentication within `Policy.step_up_max_age`; otherwise the guard answers with
the RFC 9470 challenge.
"""

# No `from __future__ import annotations`: route signatures use the local alias `P`, which FastAPI must resolve.

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import valkey
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from gateway.quotas import Quotas
from gateway.stream import SentenceStream, StreamDeps
from gateway.trust import (
    IdempotencyStore,
    PrincipalCache,
    RateLimiter,
    RevocationConsumer,
)
from identity.governance import Actor, GovernanceService
from identity.lifecycle import Notifier, co_owner_set_effect, successor_transfer_effect
from identity.scope_admin import ScopeAdmin
from lmqa_auth import PHISHING_RESISTANT
from lmqa_auth.context import ContextMinter, ContextVerifier, KmsTrustRoot, LocalTrustRoot, Signer
from lmqa_db import Claims
from lmqa_models.contracts import feature_enabled
from lmqa_models.envfile import merged_env
from lmqa_models.infra import load_infra_settings
from lmqa_models.policy import load_policy
from lmqa_models.principal import Principal
from lmqa_models.settings import Settings

log = logging.getLogger("gateway.production")


class StepUpRequired(Exception):
    def __init__(self, max_age: int) -> None:
        super().__init__("step_up_required")
        self.max_age = max_age


class StreamBody(BaseModel):
    question: str = Field(max_length=4000)


class GovernanceBody(BaseModel):
    kind: str = Field(max_length=40)
    target_id: uuid.UUID
    reason_code: str = Field(max_length=60)
    workspace_id: uuid.UUID | None = None


class MatterBody(BaseModel):
    label: str = Field(max_length=200)
    kind: str = Field(pattern="^(matter|patient)$")


class GrantBody(BaseModel):
    user_id: uuid.UUID
    max_tier: int = Field(ge=1, le=4)
    expires_at: datetime | None = None


class WallBody(BaseModel):
    user_id: uuid.UUID
    reason_code: str = Field(max_length=60)


class EmergencyBody(BaseModel):
    matter_id: uuid.UUID
    reason_code: str = Field(max_length=60)
    note: str = Field(default="", max_length=2000)


class BreakGlassBody(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class ReviewBody(BaseModel):
    outcome: str = Field(min_length=3, max_length=2000)


def _trust_root(settings: Settings) -> Any:
    env = merged_env()
    if load_infra_settings().kms_provider == "aws" and env.get("KMS_TRUST_ROOT_ID"):
        from lmqa_keys.providers import AwsKmsProvider

        return KmsTrustRoot(
            AwsKmsProvider(region=env.get("AWS_REGION", "us-east-1")), env["KMS_TRUST_ROOT_ID"]
        )
    pem_file = env.get("LMQA_TRUST_ROOT_PEM_FILE")
    if pem_file:
        from pathlib import Path

        return LocalTrustRoot(Path(pem_file).read_bytes())
    del settings
    return (
        LocalTrustRoot()
    )  # per-process root: valid while every service runs in this process (MVP deviation 1)


class ProductionServices:
    def __init__(self, settings: Settings, mvp: Any) -> None:
        self.settings = settings
        self.mvp = mvp
        self.policy = load_policy()
        infra = load_infra_settings()
        self.root = _trust_root(settings)
        from cryptography.hazmat.primitives import serialization

        self.trust_bundle = [(self.root.key_id, self.root.public_pem())]
        self.trust_roots = {
            self.root.key_id: serialization.load_pem_public_key(self.root.public_pem())
        }
        self._publish_trust_bundle(settings)
        self.gateway_signer = Signer(self.root, "gateway")
        self.validator_signer = Signer(self.root, "citation_validator")
        self.minter = ContextMinter(self.gateway_signer)
        self.verifiers = {
            aud: ContextVerifier(aud, self.trust_bundle)
            for aud in ("retrieval", "generation", "citation_validator", "identity")
        }
        self.principals = PrincipalCache()
        self.valkey: valkey.Valkey | None = None
        try:
            password = infra.valkey_password("gateway")
            self.valkey = valkey.Valkey.from_url(
                infra.valkey_url, username="gateway", password=password, socket_timeout=2
            )
        except Exception:
            self.valkey = None
        self.limits = RateLimiter(self.valkey)
        self.quotas = Quotas(self.limits, self._conn)
        self.idempotency = IdempotencyStore(self._conn)
        self.revocation = RevocationConsumer(
            self.principals,
            valkey_factory=(lambda: self.valkey) if self.valkey else None,
            on_signer_revoked=lambda kid: [v.deny(kid) for v in self.verifiers.values()],
        )
        self.governance = GovernanceService(
            self._conn,
            self.policy,
            {
                "wall_lift": ScopeAdmin.lift_wall_effect,
                "private_read_enable": ScopeAdmin.private_read_enable_effect,
                "successor_transfer": successor_transfer_effect,
                "co_owner_set": co_owner_set_effect,
            },
        )
        self.scope = ScopeAdmin(self._conn, self.policy, Notifier.enqueue)
        self.stream = SentenceStream(
            StreamDeps(
                settings=settings,
                db=mvp.db,
                retrieval=mvp.retrieval,
                validator_signer=self.validator_signer,
                trust_roots=self.trust_roots,
                register_stream=self.principals.register_stream,
                keys=mvp.keys,
                nli=self._nli(),
            )
        )

    def _publish_trust_bundle(self, settings: Settings) -> None:
        """Public keys only: workers and services verify envelopes and tokens against this bundle (9.1)."""
        import json

        path = settings.data_dir / "trust" / "bundle.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({k: pem.decode() for k, pem in self.trust_bundle}), encoding="utf-8"
        )

    def _nli(self) -> Any:
        env = merged_env()
        if not feature_enabled("pinned_nli_validator"):
            return None
        from citation_validator.nli import NliModel

        model = NliModel(
            self.settings.model_cache_dir,
            expected_sha256=env.get("NLI_MODEL_HASH"),
            threshold=float(env.get("NLI_THRESHOLD", "0.9")),
        )
        return model.supported

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        with self.mvp.db.as_service("identity", Claims(actor="gateway:production")) as conn:
            yield conn

    def start(self) -> None:
        self.revocation.start()

    def context_for(self, p: Principal, audience: str, request_id: str) -> Any:
        """Mint and verify a context token for one internal call (9.1). In one process the verify step is the
        receiving service's check, run here so the same code path is exercised before the services split."""
        m = p.membership
        assert m is not None
        token = self.minter.mint(
            audience=audience,
            sub=p.user_id,
            org_id=m.org_id,
            workspace_id=m.workspace_id,
            role=m.role,
            auth_strength="unknown",
            scope_hash="",
            scope_version=0,
            pv=0,
            request_id=request_id,
        )
        return self.verifiers[audience].verify(token)


def _actor(p: Principal, request: Request) -> Actor:
    claims = getattr(request.state, "claims", None)
    roles = {p.role} if p.role else set()
    if p.membership and p.membership.role == "super_admin":
        roles.add("super_admin")
    step_up_at = (
        datetime.fromtimestamp(claims.auth_time, UTC)
        if claims is not None and claims.auth_time and claims.auth_strength in PHISHING_RESISTANT
        else None
    )
    return Actor(
        id=p.user_id,
        kind="user",
        roles=frozenset(roles),
        authenticator_id=getattr(claims, "authenticator", None),
        step_up_at=step_up_at,
    )


def register_production_routes(app: FastAPI, svc: Any, P: Any) -> None:  # noqa: C901 - one linear flow; splitting it is a DEV-33 follow-up
    prod: ProductionServices = svc.production

    @app.post("/v1/queries/stream")
    def query_stream(
        p: P,
        body: StreamBody,
        last_event_id: str | None = Header(default=None),
        query_id: str | None = Header(default=None, alias="x-query-id"),
    ) -> StreamingResponse:
        m = p.membership
        assert m is not None and m.workspace_id is not None
        decision = prod.quotas.admit_query(
            org_id=m.org_id, workspace_id=m.workspace_id, user_id=p.user_id
        )
        if not decision.allowed:
            raise HTTPException(429, f"Too many questions ({decision.scope} limit); wait a minute.")
        prod.context_for(p, "retrieval", str(uuid.uuid4()))
        resume = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
        events = prod.stream.run(p, body.question, last_event_id=resume, query_id=query_id)
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # --- governance (6.7) ------------------------------------------------------------------------------------
    @app.get("/v1/governance")
    def governance_list(p: P) -> list[dict[str, Any]]:
        assert p.membership is not None
        return prod.governance.list_for_org(
            p.membership.org_id, opaque=p.membership.role != "admin"
        )

    @app.post("/v1/governance")
    def governance_create(p: P, body: GovernanceBody, request: Request) -> dict[str, Any]:
        assert p.membership is not None
        return prod.governance.create(
            _actor(p, request),
            org_id=p.membership.org_id,
            kind=body.kind,
            target_id=str(body.target_id),
            reason_code=body.reason_code,
            workspace_id=str(body.workspace_id) if body.workspace_id else p.membership.workspace_id,
        )

    @app.post("/v1/governance/{request_id}/{action}")
    def governance_decide(
        p: P, request_id: uuid.UUID, action: str, request: Request
    ) -> dict[str, Any]:
        actor = _actor(p, request)
        fn = {
            "approve": prod.governance.approve,
            "reject": prod.governance.reject,
            "cancel": prod.governance.cancel,
            "veto": prod.governance.veto,
        }.get(action)
        if fn is None:
            raise HTTPException(404, "Not found")
        return fn(actor, str(request_id))

    # --- matters, grants, walls (5.4 to 5.6) -----------------------------------------------------------------
    @app.get("/v1/workspace/matters")
    def matters_list(p: P) -> list[dict[str, Any]]:
        return prod.scope.list_matters(p)

    @app.post("/v1/workspace/matters")
    def matters_create(p: P, body: MatterBody) -> dict[str, Any]:
        return prod.scope.create_matter(p, body.label, body.kind)

    @app.post("/v1/workspace/matters/{matter_id}/grants")
    def grants_set(p: P, matter_id: uuid.UUID, body: GrantBody) -> dict[str, Any]:
        return prod.scope.grant(
            p, str(matter_id), str(body.user_id), body.max_tier, body.expires_at
        )

    @app.delete("/v1/workspace/matters/{matter_id}/grants/{user_id}")
    def grants_revoke(p: P, matter_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
        prod.scope.revoke_grant(p, str(matter_id), str(user_id))
        return {"status": "revoked"}

    @app.post("/v1/workspace/matters/{matter_id}/walls")
    def walls_create(p: P, matter_id: uuid.UUID, body: WallBody) -> dict[str, Any]:
        return prod.scope.create_wall(p, str(matter_id), str(body.user_id), body.reason_code)

    # --- emergency access, break-glass and reviews (5.7, 5.8) ------------------------------------------------
    @app.post("/v1/emergency-access")
    def emergency_start(p: P, body: EmergencyBody) -> dict[str, Any]:
        return prod.scope.request_emergency(p, str(body.matter_id), body.reason_code, body.note)

    @app.delete("/v1/emergency-access/{exception_id}")
    def emergency_end(p: P, exception_id: uuid.UUID) -> dict[str, str]:
        prod.scope.end_exception(p, str(exception_id))
        return {"status": "ended"}

    @app.post("/v1/break-glass")
    def break_glass_start(p: P, body: BreakGlassBody, request: Request) -> dict[str, Any]:
        return prod.scope.start_break_glass(p, body.reason, _actor(p, request).step_up_at)

    @app.delete("/v1/break-glass/{session_id}")
    def break_glass_end(p: P, session_id: uuid.UUID) -> dict[str, str]:
        prod.scope.end_break_glass(p, str(session_id))
        return {"status": "ended"}

    @app.get("/v1/reviews")
    def reviews_list(p: P) -> list[dict[str, Any]]:
        return prod.scope.list_reviews(p)

    @app.post("/v1/reviews/{task_id}/close")
    def reviews_close(p: P, task_id: uuid.UUID, body: ReviewBody) -> dict[str, str]:
        prod.scope.close_review(p, str(task_id), body.outcome)
        return {"status": "closed"}
