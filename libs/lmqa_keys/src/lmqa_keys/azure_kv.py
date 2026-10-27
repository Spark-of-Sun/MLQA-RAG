"""Azure Key Vault key provider implementing hardware-backed envelope encryption."""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from azure.identity import ClientSecretCredential, DefaultAzureCredential

from lmqa_keys.provider import DataKey, KeyProvider

if TYPE_CHECKING:
    from uuid import UUID


def _b64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string without trailing padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(encoded: str) -> bytes:
    """Decode base64url string with restored padding."""
    rem = len(encoded) % 4
    if rem > 0:
        encoded += "=" * (4 - rem)
    return base64.urlsafe_b64decode(encoded.encode("ascii"))


@dataclass(frozen=True)
class AzureKeyVaultConfig:
    """Configuration for Azure Key Vault integration."""

    vault_url: str = ""
    key_prefix: str = "lmqa-org-"
    trust_root_id: str = ""
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    @classmethod
    def from_env(cls) -> AzureKeyVaultConfig:
        """Load Key Vault configuration from environment variables."""
        return cls(
            vault_url=os.getenv("AZURE_KEYVAULT_URL", ""),
            key_prefix=os.getenv("KMS_ORG_KEY_ALIAS_PREFIX", "lmqa-org-"),
            trust_root_id=os.getenv("KMS_TRUST_ROOT_ID", ""),
            tenant_id=os.getenv("AZURE_TENANT_ID"),
            client_id=os.getenv("AZURE_CLIENT_ID"),
            client_secret=os.getenv("AZURE_CLIENT_SECRET"),
        )


class AzureKeyVaultKeyProvider(KeyProvider):
    """KeyProvider using Azure Key Vault for hardware-backed envelope encryption."""

    def __init__(
        self,
        config: AzureKeyVaultConfig | None = None,
        vault_url: str | None = None,
    ) -> None:
        """Initialize Azure Key Vault provider parameters."""
        cfg = config or AzureKeyVaultConfig.from_env()
        raw_url = vault_url or cfg.vault_url
        self.config = cfg
        self.vault_url = raw_url.rstrip("/")
        self.key_prefix = cfg.key_prefix
        self.trust_root_id = cfg.trust_root_id
        self.tenant_id = cfg.tenant_id
        self.client_id = cfg.client_id
        self.client_secret = cfg.client_secret
        self._token: str | None = None

    @classmethod
    def from_env(cls) -> AzureKeyVaultKeyProvider:
        """Construct from active environment variables."""
        return cls(config=AzureKeyVaultConfig.from_env())

    def is_configured(self) -> bool:
        """Check if Azure Key Vault URL and credentials are configured."""
        return bool(self.vault_url and not self.vault_url.startswith("https://lmqa-kv-<"))

    def _get_bearer_token(self) -> str:
        """Obtain bearer token for Azure Key Vault via Service Principal or Default Credential."""
        if not self.is_configured():
            msg = "Azure Key Vault is NOT CONFIGURED: AZURE_KEYVAULT_URL is missing or placeholder"
            raise RuntimeError(msg)

        if self.tenant_id and self.client_id and self.client_secret:
            cred = ClientSecretCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        else:
            cred = DefaultAzureCredential()

        token_obj = cred.get_token("https://vault.azure.net/.default")
        return token_obj.token

    def generate_data_key(self, org_id: UUID, key_spec: str = "AES_256") -> DataKey:
        """Generate high-entropy 256-bit plaintext key and wrap it with Key Vault key."""
        _ = key_spec
        if not self.is_configured():
            msg = "Cannot generate data key: Azure Key Vault is NOT CONFIGURED"
            raise RuntimeError(msg)

        key_name = f"{self.key_prefix}{org_id}"
        # 32 bytes = 256 bits for AES-256
        plaintext = secrets.token_bytes(32)
        plaintext_b64url = _b64url_encode(plaintext)

        token = self._get_bearer_token()
        url = f"{self.vault_url}/keys/{key_name}/wrapKey?api-version=7.5"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "alg": "RSA-OAEP-256",
            "value": plaintext_b64url,
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

            wrapped_val = str(data["value"])
            ciphertext = _b64url_decode(wrapped_val)
            key_id = str(data.get("kid", key_name))
            return DataKey(plaintext=plaintext, ciphertext=ciphertext, key_id=key_id)
        except Exception as e:
            msg = f"Azure Key Vault wrapKey failed for {key_name}: {e}"
            raise RuntimeError(msg) from e

    def decrypt_data_key(self, org_id: UUID, ciphertext: bytes) -> bytes:
        """Unwrap an Azure Key Vault ciphertext back to the original plaintext key."""
        if not self.is_configured():
            msg = "Cannot decrypt data key: Azure Key Vault is NOT CONFIGURED"
            raise RuntimeError(msg)

        key_name = f"{self.key_prefix}{org_id}"
        token = self._get_bearer_token()
        url = f"{self.vault_url}/keys/{key_name}/unwrapKey?api-version=7.5"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body = {
            "alg": "RSA-OAEP-256",
            "value": _b64url_encode(ciphertext),
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

            unwrapped_val = str(data["value"])
            return _b64url_decode(unwrapped_val)
        except Exception as e:
            msg = f"Azure Key Vault unwrapKey failed for {key_name}: {e}"
            raise RuntimeError(msg) from e
