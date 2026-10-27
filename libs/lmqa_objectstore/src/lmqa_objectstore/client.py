"""Object storage client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata for stored objects in S3."""

    key: str
    size_bytes: int
    content_type: str
    sha256_checksum: str


class ObjectStoreClient(ABC):
    """Abstract client for AWS S3 object store operations."""

    @abstractmethod
    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str,
        sha256_checksum: str,
    ) -> ObjectMetadata:
        """Store an object with integrity verification."""

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Retrieve an object by key."""

    @abstractmethod
    def delete_object(self, key: str) -> bool:
        """Delete an object by key."""
