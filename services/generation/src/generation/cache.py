"""The scoped, encrypted answer cache (doc 10.7, DEF-06, DEF-28).

The cache lives in ``generation`` and sits AFTER retrieval: retrieval always runs, so the access
filter is never skipped, and the cache only saves the expensive model call. The key is a hash of
the organization, workspace, scope hash, the retrieved chunk set (IDs and versions), the prompt
version, the model and the normalized question, so an answer built for a broad scope can never be
served to a narrower one, and any permission or document change misses.

Entries are encrypted with a random per-workspace key that rotates daily (entries expire with
it), live at most an hour, and are never shared across workspaces. Cached answers can contain PHI,
so the cache is OFF by default for medical organizations. The validator still re-checks every
cached answer against the current ledger, so a stale answer can never pass after a change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from lmqa_keys import Aad, DecryptionError, KeyService, decrypt, encrypt, new_key

if TYPE_CHECKING:
    from valkey.asyncio import Valkey

MAX_TTL_SECONDS: Final = 3600
KEY_TTL_SECONDS: Final = 2 * 86_400
_NAMESPACE: Final = UUID(int=0x1CAC4E)


@dataclass(frozen=True, slots=True)
class CacheSettings:
    """Per-organization cache policy."""

    enabled: bool
    ttl_seconds: int = MAX_TTL_SECONDS

    @classmethod
    def for_deployment(
        cls, deployment_type: str, *, opted_in: bool = False, ttl_seconds: int = MAX_TTL_SECONDS
    ) -> CacheSettings:
        """Medical (and mixed) organizations are off by default and must opt in (D12)."""
        on = opted_in if deployment_type in {"medical", "both"} else True
        return cls(enabled=on, ttl_seconds=min(ttl_seconds, MAX_TTL_SECONDS))


def normalize_question(question: str) -> str:
    """Case- and whitespace-insensitive form of a question."""
    return " ".join(question.lower().split())


def cache_key(  # noqa: PLR0913, PLR0917 - every input that can change who may see an answer
    org: UUID,
    ws: UUID,
    scope_hash: str,
    chunk_set: list[tuple[str, int]],
    prompt_version: str,
    model: str,
    question: str,
) -> str:
    """The cache key: every input that could change who may see the answer, or the answer itself."""
    material = json.dumps(
        [
            str(org),
            str(ws),
            scope_hash,
            sorted(chunk_set),
            prompt_version,
            model,
            normalize_question(question),
        ],
        separators=(",", ":"),
    )
    return f"ans:{ws}:" + hashlib.sha256(material.encode()).hexdigest()


def today() -> date:
    """The (UTC) day a cache key belongs to."""
    return datetime.now(UTC).date()


class AnswerCache:
    """Valkey-backed, encrypted, workspace-scoped."""

    def __init__(self, valkey: Valkey, keys: KeyService, settings: CacheSettings) -> None:
        """Bind the real Valkey client, the key service and the organization's policy."""
        self._v, self._keys, self._settings = valkey, keys, settings

    async def _daily_key(self, workspace_key: bytes, org: UUID, ws: UUID, day: date) -> bytes:
        """The workspace's cache key for ``day``.

        Random, stored only wrapped by the workspace key.
        """
        name = f"ckey:{ws}:{day.isoformat()}"
        aad = Aad(org, ws, uuid_for(day), 0)
        existing = await self._v.get(name)
        if existing is not None:
            return decrypt(workspace_key, bytes(existing), aad)
        fresh = new_key()
        if await self._v.set(name, encrypt(workspace_key, fresh, aad), nx=True, ex=KEY_TTL_SECONDS):
            return fresh
        return decrypt(
            workspace_key, bytes(await self._v.get(name)), aad
        )  # another replica won the race

    async def get(
        self, key: str, workspace_key: bytes, org: UUID, ws: UUID, day: date | None = None
    ) -> str | None:
        """The cached answer text, or None (disabled, missing, expired, or undecryptable)."""
        if not self._settings.enabled:
            return None
        blob = await self._v.get(key)
        if blob is None:
            return None
        try:
            ckey = await self._daily_key(workspace_key, org, ws, day or today())
            return decrypt(ckey, bytes(blob), Aad(org, ws, uuid_for(key), 0)).decode()
        except DecryptionError:
            return None  # written under yesterday's key: it expires with the key

    async def put(  # noqa: PLR0913, PLR0917 - key, answer and the scope that binds it
        self,
        key: str,
        answer: str,
        workspace_key: bytes,
        org: UUID,
        ws: UUID,
        day: date | None = None,
    ) -> bool:
        """Store an answer. Returns False when the cache is disabled for this organization."""
        if not self._settings.enabled:
            return False
        ckey = await self._daily_key(workspace_key, org, ws, day or today())
        await self._v.set(
            key,
            encrypt(ckey, answer.encode(), Aad(org, ws, uuid_for(key), 0)),
            ex=self._settings.ttl_seconds,
        )
        return True


def uuid_for(value: object) -> UUID:
    """A stable UUID for any hashable label, used to bind ciphertext to a cache name or day."""
    import uuid  # noqa: PLC0415

    return uuid.uuid5(_NAMESPACE, str(value))
