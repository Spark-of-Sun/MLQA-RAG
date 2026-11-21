"""The resume buffer for ``Last-Event-ID`` (doc 11.6, DEF-62).

Released sentences are kept for ten minutes, encrypted, keyed by request ID, so a client that
reconnects receives only sentences that were already validated, released and audited. The key is a
transient *service* secret of the Gateway (rotated with the deployment), not a workspace or
document key: the Gateway holds no key that can decrypt stored content.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING, Final, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from uuid import UUID

    from valkey.asyncio import Valkey

TTL_SECONDS: Final = 600
MAX_EVENTS: Final = 2000


class ResumeBuffer:
    """Append-only list of encrypted SSE events per request."""

    def __init__(self, valkey: Valkey, key: bytes) -> None:
        """``key`` is 32 bytes from the secret manager."""
        if len(key) != 32:  # noqa: PLR2004 - AES-256
            msg = "the resume buffer key must be 32 bytes"
            raise ValueError(msg)
        self._v, self._aes = valkey, AESGCM(key)

    def _aad(self, request_id: UUID, user_id: UUID) -> bytes:
        return f"resume|{request_id}|{user_id}".encode()

    async def append(self, request_id: UUID, user_id: UUID, event_id: int, frame: bytes) -> None:
        """Store one released event."""
        nonce = secrets.token_bytes(12)
        sealed = nonce + self._aes.encrypt(
            nonce,
            json.dumps({"id": event_id, "f": frame.decode()}).encode(),
            self._aad(request_id, user_id),
        )
        name = f"resume:{request_id}"
        await cast("Awaitable[object]", self._v.rpush(name, sealed))
        await cast("Awaitable[object]", self._v.ltrim(name, -MAX_EVENTS, -1))
        await cast("Awaitable[object]", self._v.expire(name, TTL_SECONDS))

    async def after(self, request_id: UUID, user_id: UUID, last_id: int) -> list[bytes]:
        """Events with an id greater than ``last_id``.

        For the same user only (anything else is empty).
        """
        out: list[bytes] = []
        stored = await cast("Awaitable[list[bytes]]", self._v.lrange(f"resume:{request_id}", 0, -1))
        for sealed in stored:
            raw = bytes(sealed)
            try:
                item = json.loads(
                    self._aes.decrypt(raw[:12], raw[12:], self._aad(request_id, user_id))
                )
            except InvalidTag:
                return []  # not this user's buffer: reveal nothing
            if item["id"] > last_id:
                out.append(item["f"].encode())
        return out
