"""Azure Blob Storage client adapter."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from lmqa_objectstore.client import (
    IntegrityError,
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStoreClient,
    ObjectStoreError,
)

if TYPE_CHECKING:
    from lmqa_objectstore.config import AzureStorageConfig


class AzureBlobStorageClient(ObjectStoreClient):
    """Client for Azure Blob Storage operations."""

    def __init__(self, config: AzureStorageConfig) -> None:
        """Initialize with Azure storage configuration."""
        self.config = config
        self._blob_service_client: BlobServiceClient | None = None

    def _get_service_client(self) -> BlobServiceClient:
        """Resolve Azure Blob Service Client with credential hierarchy."""
        if not self.config.is_configured():
            msg = "Azure Blob Storage is NOT CONFIGURED: account missing"
            raise ObjectStoreError(msg)

        if self._blob_service_client is not None:
            return self._blob_service_client

        account_url = f"https://{self.config.account_name}.blob.core.windows.net"

        if self.config.tenant_id and self.config.client_id and self.config.client_secret:
            credential = ClientSecretCredential(
                tenant_id=self.config.tenant_id,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
            )
            self._blob_service_client = BlobServiceClient(
                account_url=account_url, credential=credential
            )
        else:
            self._blob_service_client = BlobServiceClient(account_url=account_url)

        return self._blob_service_client

    def put_object(
        self,
        container: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        sha256_checksum: str | None = None,
    ) -> ObjectMetadata:
        """Upload a blob to Azure Blob Storage with integrity verification."""
        computed_hash = hashlib.sha256(data).hexdigest()
        if sha256_checksum and computed_hash.lower() != sha256_checksum.lower():
            msg = f"Checksum mismatch for {key}: expected {sha256_checksum}, got {computed_hash}"
            raise IntegrityError(msg)

        client = self._get_service_client()
        try:
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(key)

            filename = key.rsplit("/", maxsplit=1)[-1]
            content_settings = ContentSettings(
                content_type=content_type,
                content_disposition=f"attachment; filename={filename}",
            )
            metadata = {"sha256": computed_hash}

            blob_client.upload_blob(
                data,
                overwrite=True,
                content_settings=content_settings,
                metadata=metadata,
            )

            return ObjectMetadata(
                container=container,
                key=key,
                size_bytes=len(data),
                content_type=content_type,
                sha256_checksum=computed_hash,
            )
        except Exception as e:
            msg = f"Azure Blob upload failed for {container}/{key}: {e}"
            raise ObjectStoreError(msg) from e

    def get_object(self, container: str, key: str) -> bytes:
        """Download a blob from Azure Blob Storage."""
        client = self._get_service_client()
        try:
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(key)
            stream = blob_client.download_blob()
            return stream.readall()
        except ResourceNotFoundError as e:
            msg = f"Blob {key} not found in container {container}"
            raise ObjectNotFoundError(msg) from e
        except Exception as e:
            msg = f"Azure Blob download failed for {container}/{key}: {e}"
            raise ObjectStoreError(msg) from e

    def delete_object(self, container: str, key: str) -> bool:
        """Delete a blob from Azure Blob Storage."""
        client = self._get_service_client()
        try:
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(key)
            if not blob_client.exists():
                return False
            blob_client.delete_blob()
        except Exception as e:
            msg = f"Azure Blob delete failed for {container}/{key}: {e}"
            raise ObjectStoreError(msg) from e
        else:
            return True

    def exists(self, container: str, key: str) -> bool:
        """Check if a blob exists in Azure Blob Storage."""
        client = self._get_service_client()
        try:
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(key)
            return blob_client.exists()
        except Exception as e:
            msg = f"Azure Blob exists check failed for {container}/{key}: {e}"
            raise ObjectStoreError(msg) from e
