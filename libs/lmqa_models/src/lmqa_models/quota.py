"""Local rate-limit accounting per API key and model.

Providers reject a request once a limit is reached, and every rejected request costs the user a round trip. This
tracker counts what this process has sent, per (key, model), against each model's known limits:

  RPM  requests in the last 60 seconds
  TPM  input tokens in the last 60 seconds (estimated before sending, corrected with the provider's count after)
  RPD  requests since the daily reset (midnight Pacific time for the Gemini API)

so the client can move to another key or model *before* sending a request that would be refused. A refusal that
still happens (another process used the key, limits changed) blocks that key and model: until the daily reset for a
daily quota, for the requested delay for a per-minute one.

Keys are identified by a short SHA-256 fingerprint; the key itself is never stored or logged. Daily counts and
blocks are saved to a small JSON file so a restart does not forget them. Several processes sharing a key each count
only their own requests; the provider's refusal remains the backstop.

Key rotation per question: every question gets the next number of a persistent counter, and all of its calls
(planning, embedding, re-ranking, answer, verification) start on key ((number - 1) mod number of keys), then go on
in configured order if that key is over a limit or refuses. Question 1 starts on the first key, question 2 on the
second, and so on. Calls outside a question (indexing, doctor) use the key least used today.

The outcome of every call is counted per key and model for the day (`record`): ok, rate_limited, daily_quota,
key_rejected, unavailable, timeout, error, and skipped (refused locally, nothing sent). `make doctor` shows them.
"""

from __future__ import annotations

import atexit
import hashlib
import itertools
import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

RESET_ZONE = ZoneInfo(
    "America/Los_Angeles"
)  # Gemini API daily quotas reset at midnight Pacific time
WINDOW = 60.0
SAVE_EVERY = 2.0


@dataclass(frozen=True)
class Limits:
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None


# Free-tier limits per model (Google AI Studio rate-limit page). Override with MODEL_LIMITS in .env.
DEFAULT_LIMITS: dict[str, Limits] = {
    "gemini-3.8-flash": Limits(5, 250_000, 20),
    "gemini-3.6-flash": Limits(5, 250_000, 20),
    "gemini-3-flash-preview": Limits(5, 250_000, 20),
    "gemini-4-hydrogen": Limits(5, 250_000, 20),
    "gemini-2.5-flash": Limits(5, 250_000, 20),
    "gemini-3.5-flash-lite": Limits(15, 250_000, 500),
    "gemini-3.1-flash-lite": Limits(15, 250_000, 500),
    "gemini-3.1-flash-lite-preview": Limits(15, 250_000, 500),
    "gemini-2.5-flash-lite": Limits(10, 250_000, 20),
    "gemma-4-26b-a4b-it": Limits(30, 16_000, 14_400),
    "gemma-4-31b-it": Limits(30, 16_000, 14_400),
    "gemini-embedding-001": Limits(100, 30_000, 1_000),
    "gemini-embedding-2": Limits(100, 30_000, 1_000),
    "gemini-embedding-2-preview": Limits(100, 30_000, 1_000),
}


def parse_limits(text: str) -> dict[str, Limits]:
    """`model=RPM/TPM/RPD,...`; `-` for no limit. Example: `gemini-3.8-flash=10/1000000/500`."""
    out: dict[str, Limits] = {}
    for entry in text.split(","):
        model, sep, spec = entry.strip().partition("=")
        parts = spec.split("/")
        if not sep or not model.strip() or len(parts) != 3:
            raise ValueError(
                f"MODEL_LIMITS entry {entry.strip()!r} must look like model=RPM/TPM/RPD"
            )
        nums = [None if p.strip() in {"", "-"} else int(p.strip().replace("_", "")) for p in parts]
        out[model.strip().removeprefix("models/")] = Limits(*nums)
    return out


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:10]


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, RESET_ZONE).date().isoformat()


def next_reset(now: float) -> float:
    local = datetime.fromtimestamp(now, RESET_ZONE)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


class QuotaTracker:
    def __init__(self, limits: dict[str, Limits], path: Path | None = None) -> None:
        self._limits = limits
        self._path = path
        self._lock = threading.Lock()
        self._recent: dict[
            tuple[str, str], deque[tuple[float, int, int]]
        ] = {}  # (ts, requests, tokens)
        self._daily: dict[tuple[str, str], int] = {}
        self._day = _day(time.time())
        self._blocked: dict[
            tuple[str, str], float
        ] = {}  # (key id, model or "*") -> until (epoch seconds)
        self._calls: dict[
            tuple[str, str], dict[str, int]
        ] = {}  # (key id, model) -> outcome -> count, today
        self._questions = 0  # questions asked so far (all time): picks each question's first key
        self._dirty = False
        self._saved = 0.0
        self._load()

    # ------------------------------------------------------------------ queries
    def limits(self, model: str) -> Limits:
        return self._limits.get(model, Limits())

    def acquire(self, key_id: str, model: str, *, requests: int = 1, tokens: int = 0) -> bool:
        """Reserve capacity for one call (`requests` items, `tokens` input tokens). False: it would be refused."""
        with self._lock:
            now = time.time()
            if self._wait_locked(key_id, model, requests, tokens, now) != 0.0:
                return False
            self._recent.setdefault((key_id, model), deque()).append((now, requests, tokens))
            self._daily[(key_id, model)] = self._daily.get((key_id, model), 0) + requests
            self._touch(now)
            return True

    def wait_seconds(
        self, key_id: str, model: str, *, requests: int = 1, tokens: int = 0
    ) -> float | None:
        """Seconds until such a call fits; 0 if now; None if not before the daily reset."""
        with self._lock:
            return self._wait_locked(key_id, model, requests, tokens, time.time())

    def used_today(self, key_id: str, model: str) -> int:
        with self._lock:
            self._roll(time.time())
            return self._daily.get((key_id, model), 0)

    @property
    def questions(self) -> int:
        with self._lock:
            return self._questions

    def snapshot(self) -> list[dict[str, object]]:
        """Per key and model: requests today, call outcomes today and, if blocked, until when. For doctor."""
        with self._lock:
            now = time.time()
            self._roll(now)
            keys = set(self._daily) | set(self._calls) | {k for k in self._blocked if k[1] != "*"}
            return [
                {
                    "key": key_id,
                    "model": model,
                    "today": self._daily.get((key_id, model), 0),
                    "rpd": self.limits(model).rpd,
                    "blocked_for_s": max(0, int(self._until(key_id, model) - now)),
                    "calls": dict(sorted(self._calls.get((key_id, model), {}).items())),
                }
                for key_id, model in sorted(keys)
            ]

    # ------------------------------------------------------------------ questions and outcomes
    def next_question(self) -> int:
        """The next question's number (1, 2, ...); saved at once so a restart continues the rotation."""
        with self._lock:
            self._questions += 1
            self._touch(time.time(), force=True)
            return self._questions

    def record(self, key_id: str, model: str, outcome: str) -> None:
        """Count one call's outcome for this key and model today (see the module docstring for the outcomes)."""
        with self._lock:
            now = time.time()
            self._roll(now)
            counts = self._calls.setdefault((key_id, model), {})
            counts[outcome] = counts.get(outcome, 0) + 1
            self._touch(now)

    # ------------------------------------------------------------------ updates
    def correct_tokens(self, key_id: str, model: str, estimated: int, actual: int) -> None:
        """Replace a reservation's estimate with the provider's count."""
        if not actual or actual == estimated:
            return
        with self._lock:
            q = self._recent.get((key_id, model))
            if q:
                ts, req, _ = q[-1]
                q[-1] = (ts, req, actual)

    def block(
        self, key_id: str, model: str, *, seconds: float | None = None, daily: bool = False
    ) -> None:
        """The provider refused: skip this key and model until the daily reset, or for `seconds`."""
        with self._lock:
            now = time.time()
            until = next_reset(now) if daily else now + (seconds or WINDOW)
            if daily and (rpd := self.limits(model).rpd):
                self._daily[(key_id, model)] = max(self._daily.get((key_id, model), 0), rpd)
            self._blocked[(key_id, model)] = max(self._blocked.get((key_id, model), 0), until)
            self._touch(now, force=True)

    def block_key(self, key_id: str, seconds: float) -> None:
        """The key itself was rejected (invalid, disabled project): skip it for every model."""
        self.block(key_id, "*", seconds=seconds)

    def flush(self) -> None:
        """Save counts not yet written (saves are throttled to one per SAVE_EVERY seconds). Runs at exit."""
        with self._lock:
            if self._path and self._dirty:
                self._save(time.time())

    # ------------------------------------------------------------------ internals
    def _until(self, key_id: str, model: str) -> float:
        return max(self._blocked.get((key_id, model), 0), self._blocked.get((key_id, "*"), 0))

    def _roll(self, now: float) -> None:
        day = _day(now)
        if day != self._day:
            self._day = day
            self._daily.clear()
            self._calls.clear()
            self._dirty = True
        self._blocked = {k: v for k, v in self._blocked.items() if v > now}

    def _wait_locked(
        self, key_id: str, model: str, requests: int, tokens: int, now: float
    ) -> float | None:
        self._roll(now)
        until = self._until(key_id, model)
        if until > now:
            return None if until >= next_reset(now) - 1 else until - now
        lim = self.limits(model)
        if lim.rpd is not None and self._daily.get((key_id, model), 0) + requests > lim.rpd:
            return None
        q = self._recent.setdefault((key_id, model), deque())
        while q and q[0][0] <= now - WINDOW:
            q.popleft()
        wait = 0.0
        if lim.rpm is not None:
            wait = max(wait, _time_until_fits(q, now, lim.rpm, requests, index=1))
        if lim.tpm is not None and tokens:
            tokens = min(
                tokens, lim.tpm
            )  # one oversized call: let it wait for an empty window rather than never run
            wait = max(wait, _time_until_fits(q, now, lim.tpm, tokens, index=2))
        return wait

    def _touch(self, now: float, *, force: bool = False) -> None:
        self._dirty = True
        if self._path and (force or now - self._saved >= SAVE_EVERY):
            self._save(now)

    def _load(self) -> None:
        if not self._path or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text())
        except OSError, ValueError:
            log.warning("quota file %s is unreadable; starting with empty counters", self._path)
            return
        now = time.time()
        self._questions = int(data.get("questions", 0))
        if data.get("day") == self._day:
            self._daily = {tuple(k.split("|", 1)): int(v) for k, v in data.get("daily", {}).items()}  # type: ignore[misc]
            self._calls = {
                tuple(k.split("|", 1)): {str(o): int(n) for o, n in v.items()}  # type: ignore[misc]
                for k, v in data.get("calls", {}).items()
                if isinstance(v, dict)
            }
        self._blocked = {
            tuple(k.split("|", 1)): float(v)
            for k, v in data.get("blocked", {}).items()
            if float(v) > now
        }  # type: ignore[misc]

    def _save(self, now: float) -> None:
        assert self._path is not None
        data = {
            "day": self._day,
            "daily": {f"{k}|{m}": v for (k, m), v in self._daily.items()},
            "blocked": {f"{k}|{m}": v for (k, m), v in self._blocked.items()},
            "questions": self._questions,
            "calls": {f"{k}|{m}": v for (k, m), v in self._calls.items()},
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self._path)
            self._saved, self._dirty = now, False
        except OSError as exc:
            log.warning("could not save quota counters (%s)", type(exc).__name__)


def _time_until_fits(
    q: deque[tuple[float, int, int]], now: float, limit: int, amount: int, *, index: int
) -> float:
    """Seconds until the 60-second window has room for `amount` more (requests: index 1, tokens: index 2)."""
    used = sum(item[index] for item in q)
    if used + amount <= limit:
        return 0.0
    excess = used + amount - limit
    for item in q:  # oldest first: wait until enough of it has left the window
        excess -= item[index]
        if excess <= 0:
            return max(0.0, item[0] + WINDOW - now) + 0.05
    return WINDOW


_question: ContextVar[int | None] = ContextVar("lmqa_question", default=None)
_untracked_questions = itertools.count(
    1
)  # QUOTA_TRACKING=off: the rotation still works, but restarts at 1


def current_question() -> int | None:
    """The number of the question being answered on this thread, or None outside a question."""
    return _question.get()


@contextmanager
def question(tracker: QuotaTracker | None) -> Iterator[int]:
    """Number one question; every model and embedding call inside the block starts on that question's key."""
    n = tracker.next_question() if tracker is not None else next(_untracked_questions)
    token = _question.set(n)
    try:
        yield n
    finally:
        _question.reset(token)


def rotate[T](keys: list[T], n: int) -> list[T]:
    """Keys in the order question `n` tries them: key ((n - 1) mod len) first, then the rest in configured order."""
    if not keys:
        return keys
    i = (n - 1) % len(keys)
    return keys[i:] + keys[:i]


_trackers: dict[Path | None, QuotaTracker] = {}
_trackers_lock = threading.Lock()


def tracker_for(limits: dict[str, Limits], path: Path | None) -> QuotaTracker:
    """One tracker per counters file, shared by every client in the process (answers, planning, embeddings)."""
    with _trackers_lock:
        if path not in _trackers:
            _trackers[path] = tracker = QuotaTracker(limits, path)
            if path is not None:
                atexit.register(
                    tracker.flush
                )  # without this, counts from a process's last seconds are lost
        return _trackers[path]
