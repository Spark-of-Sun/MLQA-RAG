"""In-process sliding-window limits (single host; Valkey-backed limits are a later stage)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._trim(key, time.monotonic())) >= self.limit

    def hit(self, key: str) -> bool:
        """Record one event; True if the key is now over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._trim(key, now)
            q.append(now)
            return len(q) > self.limit
