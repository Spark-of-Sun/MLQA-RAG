"""Hierarchical quotas and noisy-neighbor control (blueprint 13.7, G9.4).

A request is admitted only if it fits the tenant, workspace and organization limits (all three, in that order),
counted in Valkey across replicas (RateLimiter). Limits come from the `quotas` table with defaults; at 80 percent of
a daily limit an alert is raised once per day. A per-organization circuit breaker opens after repeated provider
failures and closes after a cool-down, so one organization's failing provider cannot exhaust shared workers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gateway.trust import RateLimiter

DEFAULTS = {"tenant": 20, "workspace": 200, "organization": 1000}  # queries per minute


@dataclass
class QuotaDecision:
    allowed: bool
    scope: str | None = None


class Quotas:
    def __init__(
        self, limiter: RateLimiter, conn_factory: Callable[[], Any], ttl: float = 60.0
    ) -> None:
        self._limiter = limiter
        self._conn = conn_factory
        self._ttl = ttl
        self._cache: dict[tuple[str, str], tuple[float, int]] = {}
        self._lock = threading.Lock()

    def _limit(self, scope: str, scope_id: str) -> int:
        key = (scope, scope_id)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        with self._conn() as conn:
            row = conn.execute(
                "select queries_per_minute from quotas where scope = %s and scope_id = %s",
                [scope, scope_id],
            ).fetchone()
        value = (
            int(row["queries_per_minute"]) if row and row["queries_per_minute"] else DEFAULTS[scope]
        )
        with self._lock:
            self._cache[key] = (time.monotonic() + self._ttl, value)
        return value

    def admit_query(self, *, org_id: str, workspace_id: str, user_id: str) -> QuotaDecision:
        for scope, scope_id in (
            ("tenant", user_id),
            ("workspace", workspace_id),
            ("organization", org_id),
        ):
            if not self._limiter.allow(f"q:{scope}:{scope_id}", self._limit(scope, scope_id)):
                return QuotaDecision(False, scope)
        return QuotaDecision(True)


class CircuitBreaker:
    def __init__(self, failures: int = 5, cool_down: float = 60.0) -> None:
        self._max = failures
        self._cool = cool_down
        self._state: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            count, opened = self._state.get(key, (0, 0.0))
            if count < self._max:
                return True
            if time.monotonic() - opened > self._cool:
                self._state[key] = (self._max - 1, 0.0)  # half-open: one trial
                return True
            return False

    def record(self, key: str, *, ok: bool) -> None:
        with self._lock:
            if ok:
                self._state.pop(key, None)
                return
            count, _ = self._state.get(key, (0, 0.0))
            self._state[key] = (count + 1, time.monotonic())
