"""Key Provider interfaces for Envelope Encryption (Owned by Daniel Reyes)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class DataKey:
    """Envelope encryption data key."""

    plaintext: bytes
    ciphertext: bytes
    key_id: str


class KeyProvider(ABC):
    """Abstract provider for KMS / OpenBao key operations."""

    @abstractmethod
    def generate_data_key(self, org_id: UUID, key_spec: str = "AES_256") -> DataKey:
        """Generate a plaintext data key and its encrypted ciphertext."""

    @abstractmethod
    def decrypt_data_key(self, org_id: UUID, ciphertext: bytes) -> bytes:
        """Decrypt an encrypted data key back to plaintext."""
