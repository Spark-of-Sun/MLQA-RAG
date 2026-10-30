"""Key hierarchy operations and the data-key cache (doc 12.1, 12.4, 22).

Hierarchy: organization CMK (in the provider) wraps a random 256-bit *workspace content key*;
that key wraps a random *document key* locally with AES-GCM. A document key is random, never
derived, so destroying it shreds that document on its own (DEF-03).

The workspace key is cached for at most ``MAX_CACHE_TTL_SECONDS`` (15 minutes). Concurrent
callers share one provider call (single flight), so provider use is roughly
instances x active workspaces per TTL. After the TTL, an unreachable provider fails closed.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from lmqa_keys.envelope import Aad, decrypt, encrypt, new_key
from lmqa_keys.provider import KeyProvider

MAX_CACHE_TTL_SECONDS: Final = 900.0


@dataclass(frozen=True, slots=True)
class OrgKeyIds:
    """Provider key IDs created for one organization."""

    cmk_id: str
    escrow_id: str


@dataclass(slots=True)
class KeyStats:
    """Counters that let tests and metrics bound provider use."""

    wraps: int = 0
    unwraps: int = 0
    cache_hits: int = 0


@dataclass(slots=True)
class _Entry:
    key: bytes
    expires_at: float


def workspace_context(org_id: UUID, workspace_id: UUID, version: int) -> dict[str, str]:
    """The KMS encryption context for a workspace key: binds organization, workspace, version."""
    return {
        "org_id": str(org_id),
        "workspace_id": str(workspace_id),
        "purpose": "workspace-content-key",
        "version": str(version),
    }


@dataclass(slots=True)
class KeyService:
    """Create and open keys through a ``KeyProvider`` with a bounded cache."""

    provider: KeyProvider
    cache_ttl_seconds: float = MAX_CACHE_TTL_SECONDS
    stats: KeyStats = field(default_factory=KeyStats)
    _cache: dict[tuple[UUID, UUID, int], _Entry] = field(
        default_factory=dict[tuple[UUID, UUID, int], _Entry]
    )
    _locks: dict[tuple[UUID, UUID, int], asyncio.Lock] = field(
        default_factory=dict[tuple[UUID, UUID, int], asyncio.Lock]
    )

    def __post_init__(self) -> None:
        """Refuse a TTL longer than policy allows."""
        if not 0 < self.cache_ttl_seconds <= MAX_CACHE_TTL_SECONDS:
            msg = f"cache TTL must be in (0, {MAX_CACHE_TTL_SECONDS}] seconds"
            raise ValueError(msg)

    async def provision_org(self, org_id: UUID) -> OrgKeyIds:
        """Create the organization CMK and its separate escrow CMK."""
        cmk = await self.provider.create_key(f"lmqa-org-{org_id}")
        escrow = await self.provider.create_key(f"lmqa-escrow-{org_id}")
        return OrgKeyIds(cmk_id=cmk, escrow_id=escrow)

    async def new_workspace_key(
        self, cmk_id: str, org_id: UUID, workspace_id: UUID, version: int
    ) -> tuple[bytes, bytes]:
        """Create a workspace content key: ``(plaintext, wrapped)``; persist only ``wrapped``."""
        key = new_key()
        wrapped = await self.provider.wrap(
            cmk_id, key, workspace_context(org_id, workspace_id, version)
        )
        self.stats.wraps += 1
        self._cache[(org_id, workspace_id, version)] = _Entry(
            key, time.monotonic() + self.cache_ttl_seconds
        )
        return key, wrapped

    async def workspace_key(
        self, cmk_id: str, org_id: UUID, workspace_id: UUID, version: int, wrapped: bytes
    ) -> bytes:
        """Return the plaintext workspace key, from cache while fresh, else from the provider."""
        ident = (org_id, workspace_id, version)
        hit = self._cache.get(ident)
        if hit and hit.expires_at > time.monotonic():
            self.stats.cache_hits += 1
            return hit.key
        lock = self._locks.setdefault(ident, asyncio.Lock())
        async with lock:
            hit = self._cache.get(ident)
            if hit and hit.expires_at > time.monotonic():  # another caller refreshed it meanwhile
                self.stats.cache_hits += 1
                return hit.key
            self._cache.pop(ident, None)
            key = await self.provider.unwrap(
                cmk_id, wrapped, workspace_context(org_id, workspace_id, version)
            )
            self.stats.unwraps += 1
            self._cache[ident] = _Entry(key, time.monotonic() + self.cache_ttl_seconds)
            return key

    def forget_workspace(self, org_id: UUID, workspace_id: UUID) -> None:
        """Drop every cached key of a workspace (sealing, suspension, rotation)."""
        for ident in [i for i in self._cache if i[0] == org_id and i[1] == workspace_id]:
            self._cache.pop(ident, None)

    @staticmethod
    def new_document_key(
        workspace_key: bytes, org_id: UUID, workspace_id: UUID, doc_id: UUID
    ) -> tuple[bytes, bytes]:
        """Create a random document key wrapped under the workspace key: ``(key, wrapped)``."""
        key = new_key()
        return key, encrypt(workspace_key, key, Aad(org_id, workspace_id, doc_id, version=0))

    @staticmethod
    def open_document_key(
        workspace_key: bytes, wrapped: bytes | None, org_id: UUID, workspace_id: UUID, doc_id: UUID
    ) -> bytes:
        """Unwrap a document key. A destroyed key (``None``) means the document is shredded."""
        if wrapped is None:
            msg = "document key was destroyed (crypto-erased)"
            raise DocumentKeyDestroyedError(msg)
        return decrypt(workspace_key, wrapped, Aad(org_id, workspace_id, doc_id, version=0))


class DocumentKeyDestroyedError(RuntimeError):
    """The document's key no longer exists, so its content is permanently unreadable."""
