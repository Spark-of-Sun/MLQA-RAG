"""Azure Blob Storage configuration per .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AzureStorageConfig:
    """Configuration for Azure Blob Storage integration."""

    account_name: str
    container_documents: str = "documents"
    container_audit_anchors: str = "audit-anchors"
    container_tombstones: str = "tombstones"
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None

    @classmethod
    def from_env(cls) -> AzureStorageConfig:
        """Load configuration from environment variables."""
        account = os.environ.get("AZURE_STORAGE_ACCOUNT", "")
        return cls(
            account_name=account,
            container_documents=os.environ.get("AZURE_STORAGE_CONTAINER_DOCUMENTS", "documents"),
            container_audit_anchors=os.environ.get(
                "AZURE_STORAGE_CONTAINER_AUDIT_ANCHORS", "audit-anchors"
            ),
            container_tombstones=os.environ.get("AZURE_STORAGE_CONTAINER_TOMBSTONES", "tombstones"),
            tenant_id=os.environ.get("AZURE_TENANT_ID"),
            client_id=os.environ.get("AZURE_CLIENT_ID"),
            client_secret=os.environ.get("AZURE_CLIENT_SECRET"),
        )

    def is_configured(self) -> bool:
        """Check if Azure storage has an account name defined."""
        return bool(self.account_name and not self.account_name.startswith("lmqadev<"))
