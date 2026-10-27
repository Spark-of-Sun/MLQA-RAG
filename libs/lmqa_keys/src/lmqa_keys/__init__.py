"""lmqa_keys package providing Azure Key Vault, OpenBao, and local KeyProviders."""

from __future__ import annotations

import os

from lmqa_keys.azure_kv import AzureKeyVaultConfig, AzureKeyVaultKeyProvider
from lmqa_keys.local import LocalKeyProvider
from lmqa_keys.openbao import OpenBaoKeyProvider
from lmqa_keys.provider import DataKey, KeyProvider


def get_key_provider(provider_type: str | None = None) -> KeyProvider:
    """Factory to return configured KeyProvider based on environment or explicit parameter."""
    provider = (provider_type or os.getenv("KMS_PROVIDER", "local")).lower().strip()
    if provider == "azure_keyvault":
        azure_prov = AzureKeyVaultKeyProvider.from_env()
        if azure_prov.is_configured():
            return azure_prov
        # If not configured, fall back to local provider for safe offline test execution
        return LocalKeyProvider()
    if provider == "openbao":
        return OpenBaoKeyProvider.from_env()
    return LocalKeyProvider()


__all__ = [
    "AzureKeyVaultConfig",
    "AzureKeyVaultKeyProvider",
    "DataKey",
    "KeyProvider",
    "LocalKeyProvider",
    "OpenBaoKeyProvider",
    "get_key_provider",
]
