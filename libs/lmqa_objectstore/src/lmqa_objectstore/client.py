"""Object storage client interface."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ObjectStoreError(Exception):
    """Base exception for object store operations."""


class ObjectNotFoundError(ObjectStoreError):
    """Raised when a requested object is not found."""


class IntegrityError(ObjectStoreError):
    """Raised when checksum verification fails."""


class TombstoneError(ObjectStoreError):
    """Raised when accessing a document that has been shredded with a tombstone."""


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata for stored objects in object storage."""

    container: str
    key: str
    size_bytes: int
    content_type: str
    sha256_checksum: str


class ObjectStoreClient(ABC):
    """Abstract client for object store operations."""

    @abstractmethod
    def put_object(
        self,
        container: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        sha256_checksum: str | None = None,
    ) -> ObjectMetadata:
        """Store an object with integrity verification."""

    @abstractmethod
    def get_object(self, container: str, key: str) -> bytes:
        """Retrieve an object by key."""

    @abstractmethod
    def delete_object(self, container: str, key: str) -> bool:
        """Delete an object by key."""

    @abstractmethod
    def exists(self, container: str, key: str) -> bool:
        """Check if an object exists."""

    def put_document(
        self,
        tenant_id: str,
        document_id: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectMetadata:
        """Store a raw tenant document under tenant isolation prefix."""
        key = f"{tenant_id}/{document_id}"
        if self.has_tombstone(tenant_id, document_id):
            msg = f"Cannot store document {document_id}: active cryptographic tombstone"
            raise TombstoneError(msg)
        checksum = hashlib.sha256(data).hexdigest()
        return self.put_object(
            container="documents",
            key=key,
            data=data,
            content_type=content_type,
            sha256_checksum=checksum,
        )

    def get_document(self, tenant_id: str, document_id: str) -> bytes:
        """Retrieve a tenant document, failing if tombstoned."""
        if self.has_tombstone(tenant_id, document_id):
            msg = f"Document {document_id} has been shredded with a tombstone"
            raise TombstoneError(msg)
        key = f"{tenant_id}/{document_id}"
        return self.get_object(container="documents", key=key)

    def delete_document(self, tenant_id: str, document_id: str) -> bool:
        """Delete a raw tenant document."""
        key = f"{tenant_id}/{document_id}"
        return self.delete_object(container="documents", key=key)

    def put_audit_anchor(self, batch_id: str, data: bytes) -> ObjectMetadata:
        """Store an external audit trail root anchor."""
        key = f"anchors/{batch_id}.json"
        checksum = hashlib.sha256(data).hexdigest()
        return self.put_object(
            container="audit-anchors",
            key=key,
            data=data,
            content_type="application/json",
            sha256_checksum=checksum,
        )

    def get_audit_anchor(self, batch_id: str) -> bytes:
        """Retrieve an external audit root anchor."""
        key = f"anchors/{batch_id}.json"
        return self.get_object(container="audit-anchors", key=key)

    def put_tombstone(self, tenant_id: str, document_id: str, reason: str) -> ObjectMetadata:
        """Write a cryptographic shredding tombstone marker."""
        key = f"{tenant_id}/{document_id}.tombstone"
        payload = (
            f'{{"document_id": "{document_id}", "tenant_id": "{tenant_id}", "reason": "{reason}"}}'
        )
        data = payload.encode()
        checksum = hashlib.sha256(data).hexdigest()
        return self.put_object(
            container="tombstones",
            key=key,
            data=data,
            content_type="application/json",
            sha256_checksum=checksum,
        )

    def has_tombstone(self, tenant_id: str, document_id: str) -> bool:
        """Check if a document has been shredded with a tombstone."""
        key = f"{tenant_id}/{document_id}.tombstone"
        return self.exists(container="tombstones", key=key)
