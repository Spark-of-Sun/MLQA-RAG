from __future__ import annotations

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.logging import get_logger

log = get_logger(__name__)

_PUBLIC_PATHS = {"/healthz", "/docs", "/openapi.json", "/redoc"}


class _InMemoryWindow:
    """Fallback limiter used when Redis isn't reachable (e.g. unit tests).
    Not shared across gateway replicas — fine for local/dev only.
    """

    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}

    def incr(self, key: str, window_seconds: int) -> int:
        now = time.monotonic()
        count, window_start = self._counts.get(key, (0, now))
        if now - window_start >= window_seconds:
            count, window_start = 0, now
        count += 1
        self._counts[key] = (count, window_start)
        return count


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Keyed on tenant_id + user_id from the already-verified claims (this
    middleware runs closest to the route, after AuthMiddleware — see
    app/main.py for registration order). Backend is Redis (INCR + EXPIRE)
    when a Redis URL is reachable; falls back to an in-process counter
    otherwise so tests don't need a live Redis.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._limit = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
        self._fallback = _InMemoryWindow()
        self._redis = None

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis_asyncio

            # Gateway-specific cache first (see .env.local.example), falls
            # back to the shared REDIS_URL so docker-compose is unaffected.
            url = os.environ.get("GATEWAY_REDIS_URL") or os.environ.get("REDIS_URL")
            if not url:
                return None
            client = redis_asyncio.from_url(url, decode_responses=True)
            await client.ping()
            self._redis = client
            return client
        except Exception:  # any Redis failure falls back silently
            return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        claims = getattr(request.state, "claims", None)
        key = f"ratelimit:{claims.tenant_id}:{claims.user_id}" if claims else f"ratelimit:anon:{request.client.host}"

        redis_client = await self._get_redis()
        if redis_client is not None:
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 60)
        else:
            count = self._fallback.incr(key, window_seconds=60)

        if count > self._limit:
            log.warning("rate_limit_exceeded", key=key, count=count)
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})

        return await call_next(request)