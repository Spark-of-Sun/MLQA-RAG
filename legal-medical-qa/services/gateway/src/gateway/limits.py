"""Rate limits and idempotency (doc 13.7, 15.1, G3.9).

* Limits live in Valkey so they hold across Gateway replicas. If Valkey is unreachable the Gateway
  falls back to a conservative in-process limit: it degrades, it does not open.
* A state-changing request with an ``Idempotency-Key`` is applied once: a replay with the same key
  and the same request returns the stored response, a replay with a different request is refused.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from uuid import UUID

    from valkey.asyncio import Valkey

LOCAL_FALLBACK_PER_MINUTE: Final = 30
IDEMPOTENCY_TTL: Final = 24 * 3600
MAX_STORED_BODY: Final = 256 * 1024


class RateLimiter:
    """Fixed-window counters per principal and bucket, shared through Valkey."""

    def __init__(self, valkey: Valkey, per_minute: int = 240) -> None:
        """``per_minute`` is configuration (an organization's plan may tighten it)."""
        self._v, self._limit = valkey, per_minute
        self._local: dict[str, tuple[int, float]] = {}

    async def allow(self, user_id: UUID, bucket: str = "api", limit: int | None = None) -> bool:
        """Count one request; False when the principal is over the limit for this minute."""
        window = int(time.time() // 60)
        key = f"rl:{bucket}:{user_id}:{window}"
        try:
            count = int(await self._v.incr(key))
            if count == 1:
                await self._v.expire(key, 90)
        except Exception:  # noqa: BLE001 - Valkey down: a conservative local limit, never unlimited
            n, start = self._local.get(key, (0, time.monotonic()))
            self._local[key] = (n + 1, start)
            return n + 1 <= LOCAL_FALLBACK_PER_MINUTE
        return count <= (limit or self._limit)


@dataclass(frozen=True, slots=True)
class StoredResponse:
    """A response kept for replay."""

    status: int
    content_type: str
    body: bytes


class Idempotency:
    """Apply a state-changing call once per (principal, key)."""

    def __init__(self, valkey: Valkey) -> None:
        """Wrap an async Valkey client."""
        self._v = valkey

    @staticmethod
    def fingerprint(method: str, path: str, body: bytes) -> str:
        """What makes two requests 'the same request'."""
        return hashlib.sha256(f"{method}|{path}|".encode() + body).hexdigest()

    async def begin(
        self, user_id: UUID, key: str, fingerprint: str
    ) -> tuple[str, StoredResponse | None]:
        """Returns ``('new', None)``, ``('replay', response)``, ``('conflict', None)`` or ``('busy'.

        None)``.
        """
        name = f"idem:{user_id}:{hashlib.sha256(key.encode()).hexdigest()}"
        if await self._v.set(
            name, json.dumps({"fp": fingerprint, "state": "pending"}), nx=True, ex=IDEMPOTENCY_TTL
        ):
            return "new", None
        raw = json.loads(await self._v.get(name) or "{}")
        if raw.get("fp") != fingerprint:
            return "conflict", None
        if raw.get("state") != "done":
            return "busy", None
        return "replay", StoredResponse(
            int(raw["status"]), str(raw["ct"]), bytes.fromhex(raw["body"])
        )

    async def finish(
        self, user_id: UUID, key: str, fingerprint: str, response: StoredResponse
    ) -> None:
        """Store the response so a replay returns it. Large or failed responses are not kept."""
        name = f"idem:{user_id}:{hashlib.sha256(key.encode()).hexdigest()}"
        if response.status >= 500 or len(response.body) > MAX_STORED_BODY:  # noqa: PLR2004
            await self._v.delete(name)  # let the client retry a failed attempt
            return
        await self._v.set(
            name,
            json.dumps(
                {
                    "fp": fingerprint,
                    "state": "done",
                    "status": response.status,
                    "ct": response.content_type,
                    "body": response.body.hex(),
                }
            ),
            ex=IDEMPOTENCY_TTL,
        )
