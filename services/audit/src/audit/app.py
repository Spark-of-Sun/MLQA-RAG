"""The audit service (doc 4.2, 13, 15.9): read, verify and anchor.

The only code that unwraps audit keys.

Reads run under RLS in the caller's context, so a Super Admin sees org and admin events but never
payloads, an admin sees the workspace, and a tenant sees their own history. Verification
recomputes a whole hash chain. The hourly anchor writes a Merkle root over every chain head to an
Object Lock bucket in compliance mode. The anchor job needs real AWS S3 Object Lock and is not run
here (no AWS credentials).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from lmqa_audit import AuditKeyDestroyedError, AuditReader
from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims, problem
from lmqa_db import Database
from lmqa_keys import KeyProvider

Claims = Annotated[ContextClaims, Depends(context_claims())]
MAX_PAGE = 200


def merkle_root(leaves: list[bytes]) -> bytes:
    """A Merkle root over chain heads (odd levels duplicate the last node)."""
    level = [hashlib.sha256(b"\x00" + leaf).digest() for leaf in leaves] or [
        hashlib.sha256(b"").digest()
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(b"\x01" + level[i] + level[i + 1]).digest()
            for i in range(0, len(level), 2)
        ]
    return level[0]


class Anchorer:
    """Writes the hourly anchor to S3 Object Lock (compliance mode) and records it. Not run here."""

    def __init__(self, db: Database, s3: Any, bucket: str, retention_days: int = 2555) -> None:  # noqa: ANN401
        """``db`` connects as ``svc_audit_reader``.

        ``s3`` is a boto3 client with Object Lock rights.
        """
        self._db, self._s3, self._bucket, self._days = db, s3, bucket, retention_days

    async def anchor(self, ctx_system: Any) -> bytes:  # noqa: ANN401
        """Hash every chain head, write the root to the WORM bucket and record it."""
        async with self._db.scoped(ctx_system) as s:
            heads = (
                await s.execute(
                    text(
                        "SELECT chain_id, max(seq), (array_agg(hash ORDER BY seq DESC))[1] FROM "
                        "audit_event GROUP BY chain_id"
                    )
                )
            ).all()
            root = merkle_root([bytes(h[2]) for h in sorted(heads, key=lambda h: h[0])])
            key = f"anchors/{datetime.now(UTC).strftime('%Y/%m/%d/%H%M%S')}.json"
            body = json.dumps(
                {
                    "root": root.hex(),
                    "heads": {h[0]: {"seq": int(h[1]), "hash": bytes(h[2]).hex()} for h in heads},
                }
            )
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body.encode(),
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=datetime.now(UTC).replace(microsecond=0)
                + timedelta(days=self._days),
            )
            await s.execute(
                text(
                    "INSERT INTO audit_anchor (merkle_root, heads, object_key) VALUES (:r, CAST(:h "
                    "AS jsonb), :k)"
                ),
                {"r": root, "h": json.dumps({h[0]: int(h[1]) for h in heads}), "k": key},
            )
        return root


def create_app(db: Database, provider: KeyProvider, verifier: ContextVerifier) -> FastAPI:
    """Build the audit API around the real database and key provider."""
    app = FastAPI(title="audit", docs_url=None, redoc_url=None)
    app.state.verifier = verifier
    reader = AuditReader()

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/internal/v1/events")
    async def events(
        claims: Claims, limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50
    ) -> dict[str, Any]:
        async with db.scoped(claims.db_context()) as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT id, ts, action, outcome, actor_role, target, scope, reason_code "
                        "FROM audit_event"
                        " ORDER BY ts DESC LIMIT :n"
                    ),
                    {"n": limit},
                )
            ).all()
        return {
            "events": [
                {
                    "id": str(r[0]),
                    "ts": r[1].isoformat(),
                    "action": r[2],
                    "outcome": r[3],
                    "actor_role": r[4],
                    "target": r[5],
                    "scope": r[6],
                    "reason": r[7],
                }
                for r in rows
            ]
        }

    @app.get("/internal/v1/payloads/{event_id}", response_model=None)
    async def payload(event_id: UUID, claims: Claims) -> dict[str, Any] | JSONResponse:
        ctx = claims.db_context()
        async with db.scoped(ctx) as s:
            cmk = (
                await s.execute(
                    text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": ctx.org}
                )
            ).scalar()
        if cmk is None:
            return problem(404, "Not Found")
        try:
            async with db.scoped(ctx) as s:
                return {
                    "payload": await reader.read_payload(s, provider, str(cmk), ctx.org, event_id)
                }
        except LookupError:
            return problem(
                404, "Not Found"
            )  # outside the caller's scope or absent: the same answer
        except AuditKeyDestroyedError:
            return problem(410, "Payload key destroyed (retention ended)")

    @app.get("/internal/v1/verify", response_model=None)
    async def verify(claims: Claims) -> dict[str, Any] | JSONResponse:
        ctx = claims.db_context()
        chain = f"ws:{ctx.ws}" if ctx.workspace_id else f"org:{ctx.org}"
        async with db.scoped(ctx) as s:
            bad = (await s.execute(text("SELECT audit_verify(:c)"), {"c": chain})).scalar()
        return {"chain": chain, "intact": bad is None, "first_bad_seq": bad}

    return app
