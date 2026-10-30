"""OpenBao Transit adapter (doc 12.10): immediate key deletion, for shredding tests.

Keys are created ``derived`` so every encrypt and decrypt requires a *context*; a wrong context
fails inside OpenBao ("message authentication failed"), mirroring KMS encryption context.

OpenBao has no reversible "disabled" state, and deletion is immediate. ``disable``, ``enable``
and ``cancel_deletion`` therefore refuse, loudly: those behaviors are proven against real AWS KMS.
"""

from __future__ import annotations

import base64
from typing import Any, Self

import httpx

from lmqa_keys.provider import (
    ContextMismatchError,
    KeyProviderError,
    KeyState,
    KeyUnavailableError,
    canonical_context,
)

_NOT_FOUND = 404
_BAD_REQUEST = 400


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class OpenBaoProvider:
    """Async client for the Transit secrets engine."""

    name = "openbao"

    def __init__(
        self, addr: str, token: str, *, mount: str = "transit", timeout: float = 10.0
    ) -> None:
        """Connect to an OpenBao server. ``token`` comes from the environment, never from code."""
        self._mount = mount
        self._client = httpx.AsyncClient(
            base_url=addr.rstrip("/"), headers={"X-Vault-Token": token}, timeout=timeout
        )

    async def __aenter__(self) -> Self:
        """Enter the async context."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Close the HTTP client."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._client.request(method, f"/v1/{self._mount}/{path}", json=body)
        if response.status_code == _NOT_FOUND:
            msg = f"key not found or unavailable: {path}"
            raise KeyUnavailableError(msg)
        if response.status_code == _BAD_REQUEST:
            errors = " ".join(response.json().get("errors", []))
            if "authentication failed" in errors or "context" in errors:
                msg = "encryption context mismatch"
                raise ContextMismatchError(msg)
            if "not found" in errors:
                raise KeyUnavailableError(errors)
            raise KeyProviderError(errors or "bad request")
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"openbao error {response.status_code}"
            raise KeyProviderError(msg)
        if not response.content:  # e.g. 204 No Content after a key DELETE
            return {}
        return response.json().get("data") or {}

    async def create_key(self, alias: str) -> str:
        """Create a derived AES-256-GCM key that may later be deleted. The alias is the key ID."""
        await self._call("POST", f"keys/{alias}", {"type": "aes256-gcm96", "derived": True})
        await self._call("POST", f"keys/{alias}/config", {"deletion_allowed": True})
        return alias

    async def wrap(self, key_id: str, plaintext_key: bytes, context: dict[str, str]) -> bytes:
        """Encrypt a data key under ``key_id`` bound to ``context``."""
        data = await self._call(
            "POST",
            f"encrypt/{key_id}",
            {"plaintext": _b64(plaintext_key), "context": _b64(canonical_context(context))},
        )
        return str(data["ciphertext"]).encode()

    async def unwrap(self, key_id: str, wrapped: bytes, context: dict[str, str]) -> bytes:
        """Decrypt a wrapped data key; the same context must be supplied."""
        data = await self._call(
            "POST",
            f"decrypt/{key_id}",
            {"ciphertext": wrapped.decode(), "context": _b64(canonical_context(context))},
        )
        return base64.b64decode(data["plaintext"])

    async def describe(self, key_id: str) -> KeyState:
        """ENABLED while the key exists, DELETED once it is gone."""
        try:
            await self._call("GET", f"keys/{key_id}")
        except KeyUnavailableError:
            return KeyState.DELETED
        return KeyState.ENABLED

    async def disable(self, key_id: str) -> None:
        """Not supported: Transit has no reversible disabled state (use AWS KMS)."""
        msg = f"OpenBao cannot disable {key_id}; this behavior is proven on AWS KMS"
        raise KeyProviderError(msg)

    async def enable(self, key_id: str) -> None:
        """Not supported (see ``disable``)."""
        msg = f"OpenBao cannot enable {key_id}; this behavior is proven on AWS KMS"
        raise KeyProviderError(msg)

    async def schedule_deletion(self, key_id: str, window_days: int) -> None:  # noqa: ARG002
        """Delete the key immediately. The window is ignored: OpenBao has no waiting period."""
        await self._call("DELETE", f"keys/{key_id}")

    async def cancel_deletion(self, key_id: str) -> None:
        """Not supported: deletion here is immediate and irreversible."""
        msg = f"OpenBao deletion of {key_id} cannot be cancelled"
        raise KeyProviderError(msg)
