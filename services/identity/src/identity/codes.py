"""Join codes in the identity service (doc 7.6, G2.5): create, rotate and verify.

Verification is deliberately boring from the outside: every failure (malformed, unknown, wrong,
expired, exhausted, rotated, rate-limited-out) is the same ``CodeRejected`` and the same HTTP body.
The true reason goes only to ``join_attempts`` and the audit log. The lookup ID finds the row, then
a keyed HMAC is compared in constant time; for an unknown ID a dummy hash is compared so the work
done does not reveal whether a code exists. A use is counted only when a membership is created.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import text

from lmqa_db import ContextRole, DbContext
from lmqa_security.codes import CodeKind, InvalidCodeError, generate, hash_code, normalize

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from valkey.asyncio import Valkey

    from lmqa_db import Database

DEFAULTS: Final = {
    CodeKind.ORGANIZATION: (timedelta(days=30), 25),
    CodeKind.ADMIN: (timedelta(days=90), 100),
}
USER_LIMIT: Final = (5, 900)  # 5 failures per user per 15 minutes
IP_LIMIT: Final = (20, 3600)  # 20 failures per IP per hour
CODE_LIMIT: Final = (10, 900)  # a circuit breaker per lookup ID
_SYSTEM: Final = DbContext(role=ContextRole.SYSTEM)
_DUMMY: Final = b"\x00" * 32


class CodeRejected(Exception):  # noqa: N818 - this is the one uniform outcome, named for what the caller sees
    """The code was not accepted. Identical for every reason; never carries one."""


@dataclass(frozen=True, slots=True)
class VerifiedCode:
    """A code that checked out, not yet consumed."""

    code_id: UUID
    kind: CodeKind
    org_id: UUID
    workspace_id: UUID | None


class RateLimiter:
    """Fixed-window counters in real Valkey."""

    def __init__(self, valkey: Valkey) -> None:
        """Wrap an async Valkey client."""
        self._v = valkey

    async def count(self, key: str, window: int) -> int:
        """Increment and return the counter for ``key`` (expiring after ``window`` seconds)."""
        value = int(await self._v.incr(key))
        if value == 1:
            await self._v.expire(key, window)
        return value

    async def peek(self, key: str) -> int:
        """Current value without incrementing."""
        raw = await self._v.get(key)
        return int(raw) if raw else 0


class CodeService:
    """Creates codes and verifies them with uniform behaviour."""

    def __init__(
        self, db: Database, limiter: RateLimiter, peppers: dict[str, bytes], current_pepper: str
    ) -> None:
        """``peppers`` maps pepper IDs to secrets from the secret manager.

        New hashes use ``current_pepper``.
        """
        self._db, self._limiter, self._peppers, self._current = db, limiter, peppers, current_pepper

    async def create(  # noqa: PLR0913 - scope and creator are all required
        self,
        session: AsyncSession,
        kind: CodeKind,
        org_id: UUID,
        workspace_id: UUID | None,
        created_by: UUID,
        *,
        now: datetime | None = None,
    ) -> str:
        """Rotate any active code of this scope and create a new one.

        Returns the display form, shown once.
        """
        scope = "workspace_id = :w" if kind is CodeKind.ADMIN else "org_id = :o AND kind = 'org'"
        await session.execute(
            text(
                f"UPDATE join_codes SET state = 'rotated' "  # noqa: S608 - the scope clause is one of two fixed strings
                f"WHERE state IN ('active', 'disabled') AND {scope}"
            ),
            {"w": workspace_id, "o": org_id},
        )
        code = generate(kind)
        ttl, max_uses = DEFAULTS[kind]
        await session.execute(
            text(
                "INSERT INTO join_codes (kind, org_id, workspace_id, lookup_id, code_hash, "
                "pepper_id, expires_at,"
                " max_uses, created_by) VALUES (:k, :o, :w, :l, :h, :p, :e, :m, :c)"
            ),
            {
                "k": "org" if kind is CodeKind.ORGANIZATION else "admin",
                "o": org_id,
                "w": workspace_id,
                "l": code.lookup_id,
                "h": hash_code(kind, code.canonical, self._peppers[self._current]),
                "p": self._current,
                "e": (now or datetime.now(UTC)) + ttl,
                "m": max_uses,
                "c": created_by,
            },
        )
        return code.display

    async def _log(
        self, lookup: str | None, user_sub: str, ip: str | None, outcome: str, reason: str | None
    ) -> None:
        async with self._db.scoped(_SYSTEM) as s:
            await s.execute(
                text(
                    "INSERT INTO join_attempts (lookup_id, ip, outcome, true_reason) VALUES (:l, "
                    "CAST(:ip AS inet), :o, :r)"
                ),
                {
                    "l": lookup,
                    "ip": ip,
                    "o": outcome,
                    "r": f"{reason} (sub {user_sub[:12]})" if reason else None,
                },
            )

    async def verify(self, kind: CodeKind, raw: str, user_sub: str, ip: str | None) -> VerifiedCode:
        """Accept a code or raise ``CodeRejected`` (the only outward result for any failure)."""
        user_key, ip_key = f"codefail:user:{user_sub}", f"codefail:ip:{ip or 'unknown'}"
        if (await self._limiter.peek(user_key) >= USER_LIMIT[0]) or (
            await self._limiter.peek(ip_key) >= IP_LIMIT[0]
        ):
            await self._log(None, user_sub, ip, "rejected", "rate_limited")
            raise CodeRejected
        reason, lookup, found = "malformed", None, None
        try:
            canonical = normalize(raw, kind)
            lookup = canonical[:8]
            if await self._limiter.peek(f"codefail:code:{lookup}") >= CODE_LIMIT[0]:
                reason = "code_circuit_open"
            else:
                reason, found = await self._check(kind, canonical, lookup)
        except InvalidCodeError:
            pass
        if found is None:
            await self._limiter.count(user_key, USER_LIMIT[1])
            await self._limiter.count(ip_key, IP_LIMIT[1])
            if lookup:
                await self._limiter.count(f"codefail:code:{lookup}", CODE_LIMIT[1])
            await self._log(lookup, user_sub, ip, "rejected", reason)
            raise CodeRejected
        await self._log(lookup, user_sub, ip, "accepted", None)
        return found

    async def _check(
        self, kind: CodeKind, canonical: str, lookup: str
    ) -> tuple[str, VerifiedCode | None]:
        async with self._db.scoped(_SYSTEM) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT id, kind, org_id, workspace_id, code_hash, pepper_id, expires_at, "
                        "max_uses, used_count, state"
                        " FROM join_codes WHERE lookup_id = :l"
                    ),
                    {"l": lookup},
                )
            ).first()
        stored = bytes(row[4]) if row else _DUMMY
        pepper = self._peppers.get(
            str(row[5]) if row else self._current, self._peppers[self._current]
        )
        match = hmac.compare_digest(
            stored, hash_code(kind, canonical, pepper)
        )  # runs for unknown IDs too
        if row is None:
            return "unknown_lookup", None
        wanted = "org" if kind is CodeKind.ORGANIZATION else "admin"
        if not match or row[1] != wanted:
            return "wrong_secret", None
        if row[9] != "active":
            return f"state_{row[9]}", None
        if row[6] <= datetime.now(UTC):
            return "expired", None
        if row[8] >= row[7]:
            return "exhausted", None
        return "ok", VerifiedCode(row[0], kind, row[2], row[3])

    @staticmethod
    async def consume(session: AsyncSession, code: VerifiedCode) -> None:
        """Count a use; called only inside the transaction that creates the membership."""
        await session.execute(
            text("UPDATE join_codes SET used_count = used_count + 1 WHERE id = :i"),
            {"i": code.code_id},
        )
        await session.execute(
            text(
                "UPDATE join_codes SET state = 'exhausted' WHERE id = :i AND used_count >= "
                "max_uses AND state = 'active'"
            ),
            {"i": code.code_id},
        )
