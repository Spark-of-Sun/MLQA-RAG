"""Envelope encryption (doc 12.1 to 12.3): AES-256-GCM with associated data binding scope.

* ``encrypt`` / ``decrypt``: one AEAD message, ``nonce (12) || ciphertext+tag``. The associated
  data binds ``org_id``, ``workspace_id``, the object ID and its version (and a chunk ordinal when
  there is one), so ciphertext copied into another row, workspace or version fails to decrypt.
* ``encrypt_stream`` / ``decrypt_stream``: large objects in 1 MiB segments with per-segment
  nonces and a final-segment marker, so truncation is detected (doc 12.3).
"""

from __future__ import annotations

import secrets
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

KEY_BYTES: Final = 32
NONCE_BYTES: Final = 12
SEGMENT_BYTES: Final = 1024 * 1024
_STREAM_PREFIX: Final = 8
_COUNTER: Final = struct.Struct(">I")


class DecryptionError(ValueError):
    """Raised for any failure to decrypt: wrong key, wrong scope, tampering or truncation."""


@dataclass(frozen=True, slots=True)
class Aad:
    """What ciphertext is bound to. Two different values never decrypt each other's data."""

    org_id: UUID
    workspace_id: UUID
    object_id: UUID
    version: int
    ordinal: int | None = None

    def to_bytes(self) -> bytes:
        """Canonical, unambiguous serialization (fixed-width fields, no separators to confuse)."""
        ordinal = -1 if self.ordinal is None else self.ordinal
        return (
            b"lmqa/aad/v1"
            + self.org_id.bytes
            + self.workspace_id.bytes
            + self.object_id.bytes
            + struct.pack(">qq", self.version, ordinal)
        )


def new_key() -> bytes:
    """A fresh random 256-bit key. Every document and workspace key comes from here."""
    return secrets.token_bytes(KEY_BYTES)


def _check_key(key: bytes) -> None:
    if len(key) != KEY_BYTES:
        msg = "key must be 32 bytes"
        raise ValueError(msg)


def encrypt(key: bytes, plaintext: bytes, aad: Aad | bytes) -> bytes:
    """Encrypt one message. A fresh random nonce is prepended to the output."""
    _check_key(key)
    nonce = secrets.token_bytes(NONCE_BYTES)
    data = aad.to_bytes() if isinstance(aad, Aad) else aad
    return nonce + AESGCM(key).encrypt(nonce, plaintext, data)


def decrypt(key: bytes, blob: bytes, aad: Aad | bytes) -> bytes:
    """Decrypt a message produced by ``encrypt``.

    Raises:
        DecryptionError: the key, the associated data or the ciphertext does not match.
    """
    _check_key(key)
    if len(blob) < NONCE_BYTES + 16:  # nonce plus a 16-byte GCM tag
        msg = "ciphertext too short"
        raise DecryptionError(msg)
    data = aad.to_bytes() if isinstance(aad, Aad) else aad
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], data)
    except InvalidTag as exc:
        msg = "decryption failed"
        raise DecryptionError(msg) from exc


def _segment_nonce(prefix: bytes, index: int, *, final: bool) -> bytes:
    # 8 random bytes + 4-byte counter; the top bit of the counter marks the final segment.
    flagged = index | (0x80000000 if final else 0)
    return prefix + _COUNTER.pack(flagged)


def encrypt_stream(
    key: bytes, chunks: Iterable[bytes], aad: Aad, segment: int = SEGMENT_BYTES
) -> Iterator[bytes]:
    """Encrypt an object as framed segments. Yields ``prefix`` first, then ``len || segment``."""
    _check_key(key)
    prefix = secrets.token_bytes(_STREAM_PREFIX)
    aead, data = AESGCM(key), aad.to_bytes()

    def emit(index: int, part: bytes, *, final: bool) -> bytes:
        body = aead.encrypt(_segment_nonce(prefix, index, final=final), part, data)
        return struct.pack(">I", len(body)) + body

    yield prefix
    buffer, index = bytearray(), 0
    for chunk in chunks:
        buffer += chunk
        # Strictly greater: something always remains to become the marked-final segment.
        while len(buffer) > segment:
            yield emit(index, bytes(buffer[:segment]), final=False)
            del buffer[:segment]
            index += 1
    yield emit(index, bytes(buffer), final=True)


def decrypt_stream(key: bytes, frames: Iterable[bytes], aad: Aad) -> Iterator[bytes]:
    """Decrypt segments from ``encrypt_stream`` (frames are the items it yielded, in order).

    Raises:
        DecryptionError: tampering, reordering, a wrong scope, or a missing final segment.
    """
    _check_key(key)
    iterator = iter(frames)
    try:
        prefix = next(iterator)
    except StopIteration as exc:
        msg = "empty stream"
        raise DecryptionError(msg) from exc
    aead, data = AESGCM(key), aad.to_bytes()
    index, seen_final = 0, False
    for frame in iterator:
        if seen_final:
            msg = "data after the final segment"
            raise DecryptionError(msg)
        (length,) = struct.unpack(">I", frame[:4])
        body = frame[4:]
        if len(body) != length:
            msg = "corrupt segment framing"
            raise DecryptionError(msg)
        for final in (False, True):
            try:
                yield aead.decrypt(_segment_nonce(prefix, index, final=final), body, data)
            except InvalidTag:
                continue
            seen_final = final
            break
        else:
            msg = "segment failed authentication"
            raise DecryptionError(msg)
        index += 1
    if not seen_final:
        msg = "stream truncated: no final segment"
        raise DecryptionError(msg)
