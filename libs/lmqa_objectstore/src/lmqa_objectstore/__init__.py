"""Object store package providing Azure Blob and local storage adapters."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lmqa_objectstore.azure import AzureBlobStorageClient
from lmqa_objectstore.client import (
    IntegrityError,
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStoreClient,
    ObjectStoreError,
    TombstoneError,
)
from lmqa_objectstore.config import AzureStorageConfig
from lmqa_objectstore.local import LocalObjectStoreClient


def get_storage_client(
    config: AzureStorageConfig | None = None,
    local_base_dir: str | Path | None = None,
) -> ObjectStoreClient:
    """Factory to return Azure Blob client or local storage client."""
    cfg = config or AzureStorageConfig.from_env()
    if cfg.is_configured():
        return AzureBlobStorageClient(cfg)
    base = local_base_dir or (Path(tempfile.gettempdir()) / "lmqa_storage")
    return LocalObjectStoreClient(base)


__all__ = [
    "AzureBlobStorageClient",
    "AzureStorageConfig",
    "IntegrityError",
    "LocalObjectStoreClient",
    "ObjectMetadata",
    "ObjectNotFoundError",
    "ObjectStoreClient",
    "ObjectStoreError",
    "TombstoneError",
    "get_storage_client",
]
