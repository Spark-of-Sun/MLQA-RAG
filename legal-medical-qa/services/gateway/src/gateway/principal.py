"""Principal resolution and revocation (doc 8.3, 8.6, G3.2, G3.4).

The role, workspace, status and scope come from the DATABASE (``principal_v``, the only relation
the Gateway can read), never from the token. The token's own role claim is advisory: a mismatch
denies the request and raises an alert. A principal is cached in-process for at most 5 seconds
and in Valkey for at most 30 seconds; a revocation message on ``principal-invalidations`` drops
both at once, and if Valkey is unreachable the Gateway reads PostgreSQL directly. It never serves
a stale principal and never falls open.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import text

from lmqa_db import ContextRole, DbContext

if TYPE_CHECKING:
    import asyncio

    from valkey.asyncio import Valkey

    from lmqa_db import Database

LOG = logging.getLogger("gateway.principal")
INVALIDATIONS: Final = "principal-invalidations"
LOCAL_TTL: Final = 5.0
SHARED_TTL: Final = 30
_SYSTEM: Final = DbContext(role=ContextRole.SYSTEM)


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a request is, as the database says it is."""

    user_id: UUID
    sub: str
    org_id: UUID
    auth0_org_id: str | None
    workspace_id: UUID | None
    role: str
    membership_state: str
    workspace_state: str | None
    org_state: str
    principal_version: int
    scope_version: int
    scope_hash: str
    delivery_mode: str | None
    on_fail: str | None

    @property
    def active(self) -> bool:
        """True only if the membership, its workspace and the organization are all active."""
        return (
            self.membership_state == "active"
            and self.org_state == "active"
            and (self.workspace_state == "active" or self.role == "super_admin")
        )

    @property
    def role_code(self) -> str:
        """SA, AD or TE for an active member; PENDING for a member not yet approved."""
        if not self.active:
            return "PENDING" if self.membership_state == "pending_approval" else "BLOCKED"
        return {"super_admin": "SA", "admin": "AD", "tenant": "TE"}[self.role]

    def to_json(self) -> str:
        """Serialize for the shared cache."""
        return json.dumps(
            {k: str(v) if isinstance(v, UUID) else v for k, v in asdict(self).items()}
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Principal:
        """Rebuild from the shared cache."""
        d = json.loads(raw)
        for key in ("user_id", "org_id", "workspace_id"):
            d[key] = UUID(d[key]) if d.get(key) else None
        return cls(**d)


class PrincipalResolver:
    """Looks up principals with a two-level cache and listens for revocations."""

    def __init__(self, db: Database, valkey: Valkey) -> None:
        """``db`` connects as ``svc_gateway``: its only readable relation is ``principal_v``."""
        self._db, self._valkey = db, valkey
        self._local: dict[str, tuple[Principal, float]] = {}
        self._sub_of: dict[UUID, str] = {}
        self.streams: dict[UUID, set[asyncio.Event]] = {}
        self.revocations_seen = 0

    async def resolve(self, sub: str, auth0_org_id: str) -> Principal | None:
        """The principal for a verified token, or None (unknown.

        Or the token's org is not theirs).
        """
        now = time.monotonic()
        hit = self._local.get(sub)
        if hit and hit[1] > now:
            principal = hit[0]
        else:
            principal = await self._shared(sub) or await self._database(sub)
            if principal is None:
                return None
            self._local[sub] = (principal, now + LOCAL_TTL)
            self._sub_of[principal.user_id] = sub
        if principal.auth0_org_id != auth0_org_id:
            return None  # a token for another organization never resolves
        return principal

    async def _shared(self, sub: str) -> Principal | None:
        try:
            raw = await self._valkey.get(f"principal:{sub}")
        except Exception:  # noqa: BLE001 - Valkey down: read PostgreSQL directly, never a stale value
            return None
        return Principal.from_json(raw) if raw else None

    async def _database(self, sub: str) -> Principal | None:
        async with self._db.scoped(_SYSTEM) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT user_id, auth0_sub, org_id, auth0_org_id, workspace_id, role, "
                        "membership_state,"
                        " workspace_state, org_state, principal_version, scope_version, "
                        "scope_hash, delivery_mode,"
                        " on_fail FROM principal_v WHERE auth0_sub = :s"
                    ),
                    {"s": sub},
                )
            ).first()
        if row is None:
            return None
        principal = Principal(*row)
        try:
            await self._valkey.set(f"principal:{sub}", principal.to_json(), ex=SHARED_TTL)
        except Exception:  # noqa: BLE001 - the cache is an optimisation, not a dependency
            LOG.warning("principal cache unavailable; reading PostgreSQL directly")
        return principal

    async def invalidate(self, user_id: UUID) -> None:
        """Drop every cached copy of a user and cut their open streams (doc 8.6)."""
        self.revocations_seen += 1
        sub = self._sub_of.pop(user_id, None)
        if sub:
            self._local.pop(sub, None)
            try:
                await self._valkey.delete(f"principal:{sub}")
            except Exception:  # noqa: BLE001
                LOG.warning("could not delete the shared principal cache entry")
        for event in self.streams.get(user_id, set()):
            event.set()

    async def listen(self) -> None:
        """Consume revocation messages until cancelled (started with the app)."""
        pubsub = self._valkey.pubsub()
        await pubsub.subscribe(INVALIDATIONS)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    await self.invalidate(UUID(json.loads(message["data"])["user_id"]))
        finally:
            await pubsub.aclose()
