"""Unit and integration tests for lmqa_objectstore without mocks."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from lmqa_objectstore import (
    AzureBlobStorageClient,
    AzureStorageConfig,
    IntegrityError,
    LocalObjectStoreClient,
    ObjectNotFoundError,
    ObjectStoreError,
    TombstoneError,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.stage0
@pytest.mark.unit
def test_config_parsing() -> None:
    """Test AzureStorageConfig fields and environment loading."""
    cfg = AzureStorageConfig(account_name="testaccount")
    assert cfg.account_name == "testaccount"
    assert cfg.container_documents == "documents"
    assert cfg.is_configured()

    unconfigured = AzureStorageConfig(account_name="lmqadev<suffix>")
    assert not unconfigured.is_configured()


@pytest.mark.stage0
@pytest.mark.unit
def test_local_storage_crud(tmp_path: Path) -> None:
    """Test put, get, exists, and delete on real filesystem."""
    client = LocalObjectStoreClient(tmp_path)
    data = b"Hello, legal multi-tenant object storage!"
    checksum = hashlib.sha256(data).hexdigest()

    meta = client.put_object("documents", "test.txt", data, "text/plain", checksum)
    assert meta.size_bytes == len(data)
    assert meta.sha256_checksum == checksum
    assert client.exists("documents", "test.txt")

    downloaded = client.get_object("documents", "test.txt")
    assert downloaded == data

    deleted = client.delete_object("documents", "test.txt")
    assert deleted is True
    assert not client.exists("documents", "test.txt")

    with pytest.raises(ObjectNotFoundError):
        client.get_object("documents", "test.txt")


@pytest.mark.stage0
@pytest.mark.unit
def test_integrity_error_on_corrupt_checksum(tmp_path: Path) -> None:
    """Test that mismatched SHA-256 fails immediately."""
    client = LocalObjectStoreClient(tmp_path)
    data = b"Authentic payload"
    bad_checksum = "0000000000000000000000000000000000000000000000000000000000000000"

    with pytest.raises(IntegrityError):
        client.put_object("documents", "corrupt.txt", data, sha256_checksum=bad_checksum)


@pytest.mark.stage0
@pytest.mark.unit
def test_tenant_document_and_tombstone(tmp_path: Path) -> None:
    """Test tenant isolation prefix and cryptographic tombstone shredding."""
    client = LocalObjectStoreClient(tmp_path)
    tenant_id = "org_123"
    doc_id = "doc_456"
    data = b"Confidential contract agreement text"

    meta = client.put_document(tenant_id, doc_id, data, "application/pdf")
    assert meta.key == f"{tenant_id}/{doc_id}"
    assert client.get_document(tenant_id, doc_id) == data

    # Place tombstone
    assert not client.has_tombstone(tenant_id, doc_id)
    client.put_tombstone(tenant_id, doc_id, "User requested GDPR Article 17 erasure")
    assert client.has_tombstone(tenant_id, doc_id)

    # Retrieval and put must fail closed
    with pytest.raises(TombstoneError):
        client.get_document(tenant_id, doc_id)

    with pytest.raises(TombstoneError):
        client.put_document(tenant_id, doc_id, b"New content")


@pytest.mark.stage0
@pytest.mark.unit
def test_audit_anchor_storage(tmp_path: Path) -> None:
    """Test external audit anchor storage and retrieval."""
    client = LocalObjectStoreClient(tmp_path)
    anchor_payload = b'{"batch_id": "b-001", "root_hash": "abc", "count": 100}'

    meta = client.put_audit_anchor("b-001", anchor_payload)
    assert meta.container == "audit-anchors"
    assert meta.key == "anchors/b-001.json"

    retrieved = client.get_audit_anchor("b-001")
    assert retrieved == anchor_payload


@pytest.mark.stage0
@pytest.mark.unit
def test_unconfigured_azure_fails_closed() -> None:
    """Test that unconfigured AzureBlobStorageClient fails closed."""
    cfg = AzureStorageConfig(account_name="")
    client = AzureBlobStorageClient(cfg)

    with pytest.raises(ObjectStoreError, match="Azure Blob Storage is NOT CONFIGURED"):
        client.put_object("documents", "key", b"data")
