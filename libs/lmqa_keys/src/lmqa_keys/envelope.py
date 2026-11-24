"""Envelope encryption (blueprint 12.1 to 12.3).

Column values: AES-256-GCM with associated data binding `org_id`, `workspace_id`, object ID, version and purpose,
so a ciphertext copied into another row, workspace or column fails to decrypt (G1.10).

    blob = b"L1" | key_version (4 bytes, big endian) | nonce (12) | ciphertext and tag

Objects: chunked AES-256-GCM in 1 MiB segments with the STREAM construction: each segment's nonce is a random
7-byte prefix, a 4-byte counter and a 1-byte last-segment flag, so reordering, truncation and extension are all
detected.

    stream = b"LS1" | key_version (4) | prefix (7) | segments, each: length (4) | ciphertext and tag

Key wrapping below the CMK (document keys under the workspace content key) uses the same AES-GCM with associated data
naming the wrapped key's purpose and owner.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

COLUMN_MAGIC = b"L1"
STREAM_MAGIC = b"LS1"
SEGMENT = 1024 * 1024
_TAG = 16


class DecryptionError(ValueError):
    """Wrong key, wrong associated data, or tampered ciphertext. Never says which (no oracle)."""


@dataclass(frozen=True)
class Binding:
    """Associated data for one encrypted value."""

    org_id: UUID | str
    workspace_id: UUID | str | None
    object_id: UUID | str
    version: int
    purpose: str  # e.g. "chunk.text", "document.title", "query.question", "object", "doc_key"

    def aad(self) -> bytes:
        return "|".join(
            [
                "lmqa",
                self.purpose,
                str(self.org_id),
                str(self.workspace_id or "-"),
                str(self.object_id),
                str(self.version),
            ]
        ).encode()


def _check_key(key: bytes) -> None:
    if len(key) != 32:
        raise ValueError("AES-256 keys are 32 bytes")


def encrypt_value(key: bytes, key_version: int, plaintext: bytes, binding: Binding) -> bytes:
    _check_key(key)
    nonce = os.urandom(12)
    return (
        COLUMN_MAGIC
        + struct.pack(">I", key_version)
        + nonce
        + AESGCM(key).encrypt(nonce, plaintext, binding.aad())
    )


def key_version_of(blob: bytes) -> int:
    if blob[:2] != COLUMN_MAGIC or len(blob) < 2 + 4 + 12 + _TAG:
        raise DecryptionError("not an lmqa ciphertext")
    return struct.unpack(">I", blob[2:6])[0]


def decrypt_value(key: bytes, blob: bytes, binding: Binding) -> bytes:
    _check_key(key)
    key_version_of(blob)
    nonce, body = blob[6:18], blob[18:]
    try:
        return AESGCM(key).decrypt(nonce, body, binding.aad())
    except InvalidTag as exc:
        raise DecryptionError("decryption failed") from exc


def encrypt_text(key: bytes, key_version: int, text: str, binding: Binding) -> bytes:
    return encrypt_value(key, key_version, text.encode("utf-8"), binding)


def decrypt_text(key: bytes, blob: bytes, binding: Binding) -> str:
    return decrypt_value(key, blob, binding).decode("utf-8")


def wrap_key(kek: bytes, kek_version: int, key: bytes, binding: Binding) -> bytes:
    """Wrap a 32-byte key under a key-encryption key (document key under the workspace content key)."""
    _check_key(key)
    return encrypt_value(kek, kek_version, key, binding)


def unwrap_key(kek: bytes, wrapped: bytes, binding: Binding) -> bytes:
    key = decrypt_value(kek, wrapped, binding)
    _check_key(key)
    return key


# --- streaming objects -----------------------------------------------------------------------------------------


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", counter) + (b"\x01" if last else b"\x00")


def encrypt_stream(
    key: bytes, key_version: int, source: BinaryIO, binding: Binding
) -> Iterator[bytes]:
    """Yield the encrypted stream for `source`, segment by segment (constant memory)."""
    _check_key(key)
    aead = AESGCM(key)
    prefix = os.urandom(7)
    yield STREAM_MAGIC + struct.pack(">I", key_version) + prefix
    aad = binding.aad()
    counter = 0
    current = source.read(SEGMENT)
    while True:
        following = source.read(SEGMENT)
        last = not following
        sealed = aead.encrypt(_nonce(prefix, counter, last), current, aad)
        yield struct.pack(">I", len(sealed)) + sealed
        if last:
            return
        counter += 1
        current = following


def decrypt_stream(key: bytes, chunks: Iterable[bytes], binding: Binding) -> Iterator[bytes]:
    """Yield plaintext segments; raise DecryptionError on any tampering, reordering or truncation."""
    _check_key(key)
    aead = AESGCM(key)
    aad = binding.aad()
    buf = bytearray()
    it = iter(chunks)

    def need(n: int) -> bool:
        while len(buf) < n:
            try:
                buf.extend(next(it))
            except StopIteration:
                return False
        return True

    if not need(14) or bytes(buf[:3]) != STREAM_MAGIC:
        raise DecryptionError("not an lmqa stream")
    prefix = bytes(buf[7:14])
    del buf[:14]
    counter = 0
    while True:
        if not need(4):
            raise DecryptionError("stream truncated")
        size = struct.unpack(">I", buf[:4])[0]
        if size > SEGMENT + _TAG or not need(4 + size):
            raise DecryptionError("stream truncated")
        sealed = bytes(buf[4 : 4 + size])
        del buf[: 4 + size]
        more = need(1)
        try:
            plain = aead.decrypt(_nonce(prefix, counter, not more), sealed, aad)
        except InvalidTag as exc:
            raise DecryptionError("decryption failed") from exc
        yield plain
        if not more:
            return
        counter += 1


def stream_key_version(header: bytes) -> int:
    if header[:3] != STREAM_MAGIC:
        raise DecryptionError("not an lmqa stream")
    return struct.unpack(">I", header[3:7])[0]
