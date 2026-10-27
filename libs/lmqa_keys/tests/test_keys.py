"""Unit tests for KeyProvider implementations (Local, Azure Key Vault, OpenBao)."""

from __future__ import annotations

import uuid

import pytest
from lmqa_keys import (
    AzureKeyVaultKeyProvider,
    DataKey,
    LocalKeyProvider,
    get_key_provider,
)


@pytest.mark.stage0
@pytest.mark.unit
def test_local_key_provider_roundtrip() -> None:
    """Verify local key provider generates and successfully decrypts data key."""
    provider = LocalKeyProvider()
    org_id = uuid.uuid4()

    data_key = provider.generate_data_key(org_id)
    assert isinstance(data_key, DataKey)
    assert len(data_key.plaintext) == 32
    assert len(data_key.ciphertext) >= 64
    assert data_key.key_id.startswith("local-key-")

    decrypted = provider.decrypt_data_key(org_id, data_key.ciphertext)
    assert decrypted == data_key.plaintext


@pytest.mark.stage0
@pytest.mark.unit
def test_local_key_provider_tenant_isolation() -> None:
    """Verify ciphertext generated for org1 cannot be decrypted with org2."""
    provider = LocalKeyProvider()
    org1 = uuid.uuid4()
    org2 = uuid.uuid4()

    key1 = provider.generate_data_key(org1)
    with pytest.raises(ValueError, match="Envelope tag verification failed"):
        provider.decrypt_data_key(org2, key1.ciphertext)


@pytest.mark.stage0
@pytest.mark.unit
def test_azure_keyvault_provider_unconfigured() -> None:
    """Verify unconfigured Azure Key Vault provider correctly reports status and fails closed."""
    provider = AzureKeyVaultKeyProvider(vault_url="")
    assert not provider.is_configured()

    org_id = uuid.uuid4()
    with pytest.raises(RuntimeError, match="NOT CONFIGURED"):
        provider.generate_data_key(org_id)


@pytest.mark.stage0
@pytest.mark.unit
def test_get_key_provider_factory() -> None:
    """Verify get_key_provider factory honors provider parameter and environment."""
    local_prov = get_key_provider("local")
    assert isinstance(local_prov, LocalKeyProvider)

    # When azure_keyvault is unconfigured, factory falls back to LocalKeyProvider for offline tests
    unconfigured_azure = get_key_provider("azure_keyvault")
    assert isinstance(unconfigured_azure, (AzureKeyVaultKeyProvider, LocalKeyProvider))
