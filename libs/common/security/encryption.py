from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    pass


def _derive_fernet_key(raw_key: str) -> bytes:
    """FIELD_ENCRYPTION_KEY in .env can be any string; derive a valid
    32-byte urlsafe-base64 Fernet key from it deterministically so the
    same .env value always decrypts what it encrypted."""
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class FieldEncryptor:
    """Column-level encryption for PHI/privileged chunk and document
    fields, in addition to disk-level encryption — used even in local mode
    so the pattern is exercised before go-live (docs/architecture.md §7).
    """

    def __init__(self, key: str | None = None) -> None:
        raw_key = key or os.environ.get("FIELD_ENCRYPTION_KEY")
        if not raw_key:
            raise EncryptionError("FIELD_ENCRYPTION_KEY is not set")
        self._fernet = Fernet(_derive_fernet_key(raw_key))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise EncryptionError("field ciphertext invalid or key mismatch") from exc


_default_encryptor: FieldEncryptor | None = None


def _get_default() -> FieldEncryptor:
    global _default_encryptor
    if _default_encryptor is None:
        _default_encryptor = FieldEncryptor()
    return _default_encryptor


def encrypt_field(plaintext: str) -> str:
    return _get_default().encrypt(plaintext)


def decrypt_field(ciphertext: str) -> str:
    return _get_default().decrypt(ciphertext)
