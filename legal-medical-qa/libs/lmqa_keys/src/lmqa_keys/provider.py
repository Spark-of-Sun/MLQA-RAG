"""The key provider interface (doc 12.10): two real adapters, no file-backed fake (DEF-10).

* ``AwsKmsProvider``: AWS KMS, used for everything that depends on its real behavior (key
  policies, deletion windows, signing, multi-Region replicas).
* ``OpenBaoProvider``: OpenBao Transit, used for the tests that must prove shredding, because
  OpenBao allows immediate key deletion while KMS enforces a 7 to 30 day wait.

Every wrap and unwrap carries an *encryption context*. It is checked by the provider, so a key
unwrapped under the wrong organization or workspace fails inside the KMS and not only in our code.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Protocol, runtime_checkable

MIN_DELETION_WINDOW_DAYS = 7
PRODUCTION_DELETION_WINDOW_DAYS = 30


class KeyState(StrEnum):
    """Lifecycle of a provider key as the provider reports it."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class KeyProviderError(RuntimeError):
    """Raised when the provider refuses or cannot perform an operation."""


class KeyUnavailableError(KeyProviderError):
    """The key is disabled, pending deletion or deleted, so cryptographic use is refused."""


class ContextMismatchError(KeyProviderError):
    """The encryption context does not match the one used when the key was wrapped."""


def canonical_context(context: dict[str, str]) -> bytes:
    """Deterministic bytes for an encryption context (sorted keys, no whitespace)."""
    return json.dumps(context, sort_keys=True, separators=(",", ":")).encode()


@runtime_checkable
class KeyProvider(Protocol):
    """What the platform needs from a KMS. All methods are async; adapters thread blocking SDKs."""

    name: str

    async def create_key(self, alias: str) -> str:
        """Create a symmetric key and return its provider key ID."""
        ...

    async def wrap(self, key_id: str, plaintext_key: bytes, context: dict[str, str]) -> bytes:
        """Encrypt a data key under ``key_id`` bound to ``context``."""
        ...

    async def unwrap(self, key_id: str, wrapped: bytes, context: dict[str, str]) -> bytes:
        """Decrypt a wrapped data key; the same ``context`` must be supplied."""
        ...

    async def describe(self, key_id: str) -> KeyState:
        """Report the key's lifecycle state."""
        ...

    async def disable(self, key_id: str) -> None:
        """Stop cryptographic use without scheduling deletion (reversible)."""
        ...

    async def enable(self, key_id: str) -> None:
        """Re-enable a disabled key."""
        ...

    async def schedule_deletion(self, key_id: str, window_days: int) -> None:
        """Schedule deletion. Production keys always use the 30 day maximum."""
        ...

    async def cancel_deletion(self, key_id: str) -> None:
        """Cancel a scheduled deletion (the key stays disabled until enabled)."""
        ...
