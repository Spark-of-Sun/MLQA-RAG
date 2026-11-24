"""Gateway trust components (blueprint 8.5, 8.6, 9, 15, G3.2 to G3.10).

* `PrincipalCache` + `RevocationConsumer`: principals are resolved from `principal_v` and cached for at most 30 s;
  a revocation message (Valkey `revocation:principal`, or the PostgreSQL `lmqa_revocation` NOTIFY as fallback)
  drops the entry and cuts the user's open streams at once. SLO: p99 <= 2 s with pub/sub healthy, <= 5 s without.
* `RateLimiter`: a sliding-window counter in Valkey shared by every replica; when Valkey is down it falls back to a
  conservative per-process limit (half the configured rate), so decisions stay correct and never fail open.
* `IdempotencyStore`: `Idempotency-Key` on state-changing calls; a replay with the same key and body returns the
  original response; a different body with the same key is a 409.
* `step_up_challenge`: the RFC 9470 response when authentication is too old or too weak.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import valkey
from fastapi.responses import JSONResponse

from lmqa_auth.strength import PHISHING_RESISTANT, at_least

log = logging.getLogger("gateway.trust")
REVOCATION_CHANNEL = "revocation:principal"
SIGNER_REVOCATION_CHANNEL = "revocation:signer"
PRINCIPAL_TTL = 30.0


# --- principals and revocation --------------------------------------------------------------------------------


@dataclass
class _Entry:
    value: Any
    expires: float
    pv: int | None


class PrincipalCache:
    def __init__(self, ttl: float = PRINCIPAL_TTL) -> None:
        self._ttl = ttl
        self._items: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._stream_cancels: dict[str, set[Callable[[], None]]] = defaultdict(set)

    def get(self, sub: str) -> Any | None:
        with self._lock:
            entry = self._items.get(sub)
            if entry and entry.expires > time.monotonic():
                return entry.value
            self._items.pop(sub, None)
            return None

    def put(self, sub: str, value: Any, pv: int | None = None) -> None:
        with self._lock:
            self._items[sub] = _Entry(value, time.monotonic() + self._ttl, pv)

    def register_stream(self, user_id: str, cancel: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._stream_cancels[user_id].add(cancel)

        def done() -> None:
            with self._lock:
                self._stream_cancels[user_id].discard(cancel)

        return done

    def revoke(self, user_id: str) -> int:
        """Drop cached principals of `user_id` (keyed by sub, so scan values) and cancel its open streams."""
        with self._lock:
            for sub in [
                s for s, e in self._items.items() if getattr(e.value, "user_id", None) == user_id
            ]:
                del self._items[sub]
            cancels = list(self._stream_cancels.pop(user_id, set()))
        for cancel in cancels:
            cancel()
        return len(cancels)


class RevocationConsumer:
    """Subscribes to Valkey; falls back to PostgreSQL LISTEN when Valkey is unreachable."""

    def __init__(
        self,
        cache: PrincipalCache,
        *,
        valkey_factory: Callable[[], valkey.Valkey] | None,
        pg_listen: Callable[[Callable[[str], None]], None] | None = None,
        on_signer_revoked: Callable[[str], None] | None = None,
    ) -> None:
        self._cache = cache
        self._valkey = valkey_factory
        self._pg_listen = pg_listen
        self._on_signer = on_signer_revoked
        self._stop = threading.Event()
        self.received = 0

    def handle(self, message: str) -> None:
        user_id = message.split(":", 1)[0]
        self.received += 1
        n = self._cache.revoke(user_id)
        log.info("revocation applied (streams cut: %d)", n)

    def start(self) -> None:
        if self._valkey:
            threading.Thread(target=self._run_valkey, name="revocation-valkey", daemon=True).start()
        if self._pg_listen:
            threading.Thread(
                target=self._pg_listen, args=(self.handle,), name="revocation-pg", daemon=True
            ).start()

    def stop(self) -> None:
        self._stop.set()

    def _run_valkey(self) -> None:
        assert self._valkey is not None
        while not self._stop.is_set():
            try:
                client = self._valkey()
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(REVOCATION_CHANNEL, SIGNER_REVOCATION_CHANNEL)
                while not self._stop.is_set():
                    msg = pubsub.get_message(timeout=1.0)
                    if not msg:
                        continue
                    data = (
                        msg["data"].decode() if isinstance(msg["data"], bytes) else str(msg["data"])
                    )
                    channel = (
                        msg["channel"].decode()
                        if isinstance(msg["channel"], bytes)
                        else str(msg["channel"])
                    )
                    if channel == SIGNER_REVOCATION_CHANNEL and self._on_signer:
                        self._on_signer(data)
                    else:
                        self.handle(data)
            except valkey.exceptions.ConnectionError, valkey.exceptions.TimeoutError, OSError:
                time.sleep(1.0)  # the PostgreSQL listener keeps working meanwhile


# --- rate limits ----------------------------------------------------------------------------------------------


class RateLimiter:
    _LUA = """
    local key, now, window, limit = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local n = redis.call('ZCARD', key)
    if n >= limit then return 0 end
    redis.call('ZADD', key, now, ARGV[4])
    redis.call('PEXPIRE', key, window)
    return 1
    """

    def __init__(self, client: valkey.Valkey | None) -> None:
        self._client = client
        self._script = client.register_script(self._LUA) if client else None
        self._local: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self.fallbacks = 0

    def allow(self, scope: str, limit: int, window_seconds: float = 60.0) -> bool:
        now_ms = int(time.time() * 1000)
        if self._script is not None:
            try:
                member = f"{now_ms}-{threading.get_ident()}-{time.perf_counter_ns()}"
                return bool(
                    self._script(
                        keys=[f"rl:{scope}"],
                        args=[now_ms, int(window_seconds * 1000), limit, member],
                    )
                )
            except valkey.exceptions.ConnectionError, valkey.exceptions.TimeoutError, OSError:
                self.fallbacks += 1
        return self._allow_local(scope, max(1, limit // 2), window_seconds)

    def _allow_local(self, scope: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._local[scope]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


# --- idempotency ----------------------------------------------------------------------------------------------


class IdempotencyConflictError(Exception):
    pass


class IdempotencyStore:
    """Backed by the `idempotency_keys` table (24 h), written in the same transaction as the action's audit."""

    def __init__(self, conn_factory: Callable[[], Any]) -> None:
        self._conn = conn_factory

    @staticmethod
    def digest(method: str, path: str, body: bytes) -> str:
        return hashlib.sha256(method.encode() + b"\0" + path.encode() + b"\0" + body).hexdigest()

    def lookup(self, user_id: str, key: str, digest: str) -> tuple[int, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "select request_sha256, status_code, response from idempotency_keys"
                " where user_id = %s and key = %s and expires_at > now()",
                [user_id, key],
            ).fetchone()
        if not row:
            return None
        if row["request_sha256"] != digest:
            raise IdempotencyConflictError
        return (
            (int(row["status_code"]), row["response"]) if row["status_code"] is not None else None
        )

    def store(  # noqa: PLR0913, PLR0917 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        user_id: str,
        key: str,
        method: str,
        path: str,
        digest: str,
        status: int,
        response: Any,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "insert into idempotency_keys (key, user_id, method, path, request_sha256, status_code, response)"
                " values (%s, %s, %s, %s, %s, %s, %s::jsonb) on conflict (user_id, key) do nothing",
                [key, user_id, method, path, digest, status, json.dumps(response, default=str)],
            )


# --- step-up (RFC 9470) ---------------------------------------------------------------------------------------


def needs_step_up(strength: str, auth_time: int | None, *, required: str, max_age: int) -> bool:
    if not at_least(strength, required):
        return True
    return auth_time is None or time.time() - auth_time > max_age


def step_up_challenge(required: str, max_age: int) -> JSONResponse:
    acr = "urn:lmqa:acr:passkey" if required in PHISHING_RESISTANT else "urn:lmqa:acr:mfa"
    header = (
        f'Bearer error="insufficient_user_authentication", '
        f'error_description="A stronger or more recent authentication is required", '
        f'acr_values="{acr}", max_age={max_age}'
    )
    return JSONResponse(
        {"detail": "step_up_required", "acr_values": acr, "max_age": max_age},
        status_code=401,
        headers={"WWW-Authenticate": header},
    )
