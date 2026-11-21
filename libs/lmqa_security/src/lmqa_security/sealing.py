"""HPKE sealing of audit payloads (doc 13.2, RFC 9180).

Writers hold only the *public* key, so they can encrypt but never decrypt. Only the audit
service unwraps the month's private key. Suite: DHKEM(X25519, HKDF-SHA256), HKDF-SHA256,
AES-256-GCM, base mode. The output is ``enc || ciphertext`` so it is one opaque blob.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Final

from pyhpke import AEADId, CipherSuite, KDFId, KEMId

_SUITE: Final = CipherSuite.new(
    KEMId.DHKEM_X25519_HKDF_SHA256, KDFId.HKDF_SHA256, AEADId.AES256_GCM
)
ENC_LENGTH: Final = 32
"""Length of the X25519 encapsulated key that prefixes every sealed blob."""
INFO: Final = b"lmqa/audit-payload/v1"


class SealError(ValueError):
    """Raised when a sealed payload cannot be opened (wrong key, wrong context, tampering)."""


@dataclass(frozen=True, slots=True)
class SealKeyPair:
    """An X25519 key pair as raw bytes. Store the private half only wrapped by the KMS."""

    public: bytes
    private: bytes


def generate_keypair() -> SealKeyPair:
    """Create a fresh key pair for one workspace-month."""
    pair = _SUITE.kem.derive_key_pair(secrets.token_bytes(32))
    return SealKeyPair(
        public=pair.public_key.to_public_bytes(), private=pair.private_key.to_private_bytes()
    )


def seal(public_key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt to ``public_key``, binding ``aad`` (org, workspace, event, month)."""
    pkr = _SUITE.kem.deserialize_public_key(public_key)
    enc, sender = _SUITE.create_sender_context(pkr, info=INFO)
    return enc + sender.seal(plaintext, aad=aad)


def open_sealed(private_key: bytes, sealed: bytes, aad: bytes) -> bytes:
    """Decrypt a blob produced by ``seal``.

    Raises:
        SealError: the key, the ``aad`` or the blob does not match.
    """
    if len(sealed) <= ENC_LENGTH:
        msg = "sealed payload is too short"
        raise SealError(msg)
    try:
        skr = _SUITE.kem.deserialize_private_key(private_key)
        recipient = _SUITE.create_recipient_context(sealed[:ENC_LENGTH], skr, info=INFO)
        return recipient.open(sealed[ENC_LENGTH:], aad=aad)
    except Exception as exc:
        msg = "cannot open sealed payload"
        raise SealError(msg) from exc
