"""Local in-memory KeyProvider implementation for offline testing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

from lmqa_keys.provider import DataKey, KeyProvider

if TYPE_CHECKING:
    from uuid import UUID

ENVELOPE_MIN_LEN = 64


class LocalKeyProvider(KeyProvider):
    """Local, offline key provider for unit testing without external KMS dependencies."""

    def __init__(self, master_seed: bytes | None = None) -> None:
        """Initialize with optional deterministic seed or random master key."""
        self._master_key = master_seed or secrets.token_bytes(32)

    def _derive_org_key(self, org_id: UUID) -> bytes:
        """Derive an org-specific wrapping key from the master seed."""
        return hmac.new(self._master_key, str(org_id).encode("utf-8"), hashlib.sha256).digest()

    def generate_data_key(self, org_id: UUID, key_spec: str = "AES_256") -> DataKey:
        """Generate a random 32-byte plaintext key and its encrypted envelope."""
        _ = key_spec
        plaintext = secrets.token_bytes(32)
        org_key = self._derive_org_key(org_id)

        # Mask plaintext with keystream derived from org_key and a nonce
        nonce = secrets.token_bytes(16)
        keystream = hashlib.sha256(org_key + nonce).digest()
        cipher_bytes = bytes(p ^ k for p, k in zip(plaintext, keystream, strict=True))
        tag = hmac.new(org_key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]

        ciphertext = nonce + tag + cipher_bytes
        key_id = f"local-key-{str(org_id)[:8]}"
        return DataKey(plaintext=plaintext, ciphertext=ciphertext, key_id=key_id)

    def decrypt_data_key(self, org_id: UUID, ciphertext: bytes) -> bytes:
        """Decrypt an encrypted envelope data key back to plaintext."""
        if len(ciphertext) < ENVELOPE_MIN_LEN:  # 16 nonce + 16 tag + 32 payload
            msg = "Ciphertext too short to contain valid envelope"
            raise ValueError(msg)

        nonce = ciphertext[:16]
        tag = ciphertext[16:32]
        cipher_bytes = ciphertext[32:64]

        org_key = self._derive_org_key(org_id)
        expected_tag = hmac.new(org_key, nonce + cipher_bytes, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            msg = "Envelope tag verification failed: corrupted ciphertext or wrong org_id"
            raise ValueError(msg)

        keystream = hashlib.sha256(org_key + nonce).digest()
        return bytes(c ^ k for c, k in zip(cipher_bytes, keystream, strict=True))
