"""Filesystem-backed object store client for real offline testing and local CI."""

from __future__ import annotations

import hashlib
from pathlib import Path

from lmqa_objectstore.client import (
    IntegrityError,
    ObjectMetadata,
    ObjectNotFoundError,
    ObjectStoreClient,
)


class LocalObjectStoreClient(ObjectStoreClient):
    """Real filesystem storage engine implementing ObjectStoreClient without mocks."""

    def __init__(self, base_dir: Path | str) -> None:
        """Initialize with a root storage directory."""
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, container: str, key: str) -> Path:
        """Resolve safe local path for container and key."""
        clean_key = str(Path(key))
        if clean_key.startswith(("/", "\\", "..")):
            clean_key = clean_key.lstrip("/\\.").replace("..", "")
        return self.base_dir / container / clean_key

    def put_object(
        self,
        container: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        sha256_checksum: str | None = None,
    ) -> ObjectMetadata:
        """Store an object to local filesystem with SHA-256 integrity."""
        computed_hash = hashlib.sha256(data).hexdigest()
        if sha256_checksum and computed_hash.lower() != sha256_checksum.lower():
            msg = f"Checksum mismatch for {key}: expected {sha256_checksum}, got {computed_hash}"
            raise IntegrityError(msg)

        target_path = self._get_path(container, key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)

        return ObjectMetadata(
            container=container,
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            sha256_checksum=computed_hash,
        )

    def get_object(self, container: str, key: str) -> bytes:
        """Retrieve an object from local filesystem."""
        target_path = self._get_path(container, key)
        if not target_path.is_file():
            msg = f"Object {key} not found in container {container}"
            raise ObjectNotFoundError(msg)
        return target_path.read_bytes()

    def delete_object(self, container: str, key: str) -> bool:
        """Delete an object from local filesystem."""
        target_path = self._get_path(container, key)
        if target_path.is_file():
            target_path.unlink()
            return True
        return False

    def exists(self, container: str, key: str) -> bool:
        """Check if an object exists on local filesystem."""
        target_path = self._get_path(container, key)
        return target_path.is_file()
