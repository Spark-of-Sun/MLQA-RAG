"""Valkey-backed stores for internal trust (doc 9.1, 8.6): deny list and single-use token IDs.

Real Valkey only; these are thin wrappers so tests and services use the identical code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from valkey.asyncio import Valkey

DENY_PREFIX: Final = "trust:deny:"
JTI_PREFIX: Final = "trust:jti:"


class ValkeyDenyList:
    """Revoked signer certificates. One entry revokes a pod's key (doc 9.1)."""

    def __init__(self, client: Valkey) -> None:
        """Wrap an async Valkey client."""
        self._client = client

    async def deny(self, cert_id: str, ttl_seconds: int = 7200) -> None:
        """Revoke a certificate until it would have expired anyway."""
        await self._client.set(f"{DENY_PREFIX}{cert_id}", "1", ex=ttl_seconds)

    async def is_denied(self, cert_id: str) -> bool:
        """True if the certificate is on the deny list."""
        return bool(await self._client.exists(f"{DENY_PREFIX}{cert_id}"))


class ValkeyJtiStore:
    """Single-use ``jti`` records: ``SET NX`` makes a reuse detectable across replicas."""

    def __init__(self, client: Valkey) -> None:
        """Wrap an async Valkey client."""
        self._client = client

    async def claim(self, jti: str, ttl_seconds: int) -> bool:
        """Return True the first time ``jti`` is seen, False on any reuse."""
        return bool(await self._client.set(f"{JTI_PREFIX}{jti}", "1", nx=True, ex=ttl_seconds))
