"""OpenBao transit secrets engine key provider for immediate-shred drills."""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx

from lmqa_keys.provider import DataKey, KeyProvider

if TYPE_CHECKING:
    from uuid import UUID

HTTP_OK = 200


class OpenBaoKeyProvider(KeyProvider):
    """OpenBao transit engine key provider for fast cryptographic shredding."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        key_prefix: str = "lmqa-org-",
    ) -> None:
        """Initialize OpenBao parameters."""
        self.base_url = (base_url or os.getenv("OPENBAO_URL", "http://localhost:8200")).rstrip("/")
        self.token = token or os.getenv("OPENBAO_DEV_ROOT_TOKEN", "root")
        self.key_prefix = key_prefix
        self.headers = {"X-Vault-Token": self.token, "Content-Type": "application/json"}

    @classmethod
    def from_env(cls) -> OpenBaoKeyProvider:
        """Construct from active environment variables."""
        return cls()

    def _ensure_transit_key(self, key_name: str) -> None:
        """Ensure the transit key exists in OpenBao."""
        url = f"{self.base_url}/v1/transit/keys/{key_name}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url, headers=self.headers)
                if resp.status_code == HTTP_OK:
                    return
                # Create transit key
                create_resp = client.post(url, headers=self.headers, json={"type": "aes256-gcm96"})
                create_resp.raise_for_status()
        except Exception as e:
            msg = f"Failed to ensure OpenBao transit key {key_name}: {e}"
            raise RuntimeError(msg) from e

    def generate_data_key(self, org_id: UUID, key_spec: str = "AES_256") -> DataKey:
        """Request OpenBao transit engine to generate a high-entropy data key."""
        _ = key_spec
        key_name = f"{self.key_prefix}{org_id}"
        self._ensure_transit_key(key_name)

        url = f"{self.base_url}/v1/transit/datakey/plaintext/{key_name}"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, headers=self.headers, json={"bits": 256})
                resp.raise_for_status()
                data: dict[str, Any] = resp.json().get("data", {})

            plaintext_b64 = str(data["plaintext"])
            ciphertext_str = str(data["ciphertext"])
            plaintext = base64.b64decode(plaintext_b64)
            ciphertext = ciphertext_str.encode("utf-8")
            return DataKey(plaintext=plaintext, ciphertext=ciphertext, key_id=key_name)
        except Exception as e:
            msg = f"OpenBao generate_data_key failed for {key_name}: {e}"
            raise RuntimeError(msg) from e

    def decrypt_data_key(self, org_id: UUID, ciphertext: bytes) -> bytes:
        """Decrypt an OpenBao transit ciphertext back to raw plaintext bytes."""
        key_name = f"{self.key_prefix}{org_id}"
        ciphertext_str = ciphertext.decode("utf-8")
        url = f"{self.base_url}/v1/transit/decrypt/{key_name}"

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, headers=self.headers, json={"ciphertext": ciphertext_str})
                resp.raise_for_status()
                data: dict[str, Any] = resp.json().get("data", {})

            plaintext_b64 = str(data["plaintext"])
            return base64.b64decode(plaintext_b64)
        except Exception as e:
            msg = f"OpenBao decrypt_data_key failed for {key_name}: {e}"
            raise RuntimeError(msg) from e
