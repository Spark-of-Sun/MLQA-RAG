"""Ops API (blueprint 4.2 port 8006, 14): exposed only on the operator ingress, authenticated against the operator
identity provider (`OPS_AUTH0_DOMAIN`, `OPS_AUDIENCE`), never a customer tenant. Operators' roles come from
`ops.operator_accounts`, not from token claims.

    uvicorn ops.app:create_app --factory --host 127.0.0.1 --port 8006
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from identity.governance import Actor, GovernanceService
from lmqa_db import Claims, Database
from lmqa_models.envfile import merged_env
from lmqa_models.errors import ServiceError
from lmqa_models.policy import load_policy
from lmqa_models.settings import load_settings
from ops.jit import JitAccess, Operator


class AccessRequest(BaseModel):
    org_id: UUID
    plane: str = Field(pattern="^(infrastructure|control|content)$")
    reason: str = Field(min_length=10, max_length=2000)
    ticket: str = Field(min_length=3, max_length=100)
    workspace_id: UUID | None = None
    hours: float = Field(default=1.0, gt=0, le=24)


def create_app() -> FastAPI:  # noqa: C901 - one linear flow; splitting it is a DEV-33 follow-up
    settings = load_settings()
    env = merged_env()
    db = Database(settings, services=("ops",))
    policy = load_policy()

    @contextmanager
    def conn() -> Iterator[Any]:
        with db.as_service("ops", Claims(actor="ops")) as c:
            yield c

    jit = JitAccess(conn, policy)
    governance = GovernanceService(conn, policy)
    domain = env.get("OPS_AUTH0_DOMAIN", "")
    audience = env.get("OPS_AUDIENCE", "")
    jwks = jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json") if domain else None

    app = FastAPI(
        title="LMQA Ops",
        docs_url=None,
        redoc_url=None,
        on_startup=[db.open],
        on_shutdown=[db.close],
    )

    @app.exception_handler(ServiceError)
    async def _err(_: Request, exc: ServiceError) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    def operator(request: Request) -> Operator:
        header = request.headers.get("authorization", "")
        if not jwks or not header.lower().startswith("bearer "):
            raise HTTPException(401, "Unauthorized")
        try:
            token = header[7:]
            claims = jwt.decode(
                token,
                jwks.get_signing_key_from_jwt(token).key,
                algorithms=["RS256"],
                audience=audience,
                issuer=f"https://{domain}/",
            )
        except jwt.PyJWTError, ValueError:
            raise HTTPException(401, "Unauthorized") from None
        if claims.get("https://ops.onekami.site/auth_strength") not in {"passkey", "passkey_mfa"}:
            raise HTTPException(401, "passkey required")
        with db.as_service("ops", Claims(actor="ops")) as c:
            row = c.execute(
                "select id, roles from ops.operator_accounts where idp_subject = %s and state = 'active'",
                [claims["sub"]],
            ).fetchone()
        if not row:
            raise HTTPException(403, "not an operator")
        request.state.authenticator = claims.get("https://ops.onekami.site/authenticator")
        return Operator(str(row["id"]), frozenset(row["roles"]))

    Op = Annotated[Operator, Depends(operator)]

    @app.post("/ops/v1/access")
    def request_access(op: Op, body: AccessRequest) -> dict[str, Any]:
        return jit.request(
            op,
            org_id=str(body.org_id),
            plane=body.plane,
            reason=body.reason,
            ticket=body.ticket,
            workspace_id=str(body.workspace_id) if body.workspace_id else None,
            hours=body.hours,
        )

    @app.post("/ops/v1/access/{grant_id}/approve")
    def approve_access(op: Op, grant_id: UUID) -> dict[str, Any]:
        return jit.approve_as_operator(op, str(grant_id))

    @app.post("/ops/v1/access/{grant_id}/revoke")
    def revoke_access(op: Op, grant_id: UUID) -> dict[str, str]:
        jit.revoke(str(grant_id), op.id)
        return {"status": "revoked"}

    @app.post("/ops/v1/governance/{request_id}/{action}")
    def keyguard_decide(op: Op, request_id: UUID, action: str, request: Request) -> dict[str, Any]:
        """Custodian and security-officer decisions on governance requests (12.6, 14.3)."""
        from datetime import UTC, datetime

        actor = Actor(
            op.id,
            "operator",
            op.roles,
            getattr(request.state, "authenticator", None),
            datetime.now(UTC),
        )
        fn = {"approve": governance.approve, "reject": governance.reject}.get(action)
        if fn is None:
            raise HTTPException(404, "Not found")
        return fn(actor, str(request_id))

    return app
