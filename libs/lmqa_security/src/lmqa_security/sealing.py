"""Seal audit payloads to a public key (blueprint 13.2, D31, KD-10): HPKE base mode, RFC 9180.

The implementation is `cryptography`'s `hazmat.primitives.hpke` (OpenSSL), not our own. Suite: DHKEM(X25519,
HKDF-SHA256), HKDF-SHA256, AES-256-GCM. Writers hold only the public key of one workspace (or the organization
control chain) for one calendar month, so they cannot read what they wrote; the audit service holds the private keys
(wrapped under the organization CMK in `audit_keys`). `info` binds the ciphertext to the organization, the workspace,
the month and the event action, so a sealed payload copied to another chain, month or action does not open.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite

SUITE = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)
FORMAT = b"lmqa-audit-v2"


def _info(org_id: UUID | str, workspace_id: UUID | str | None, month: date, action: str) -> bytes:
    return b"|".join(
        [
            FORMAT,
            str(org_id).encode(),
            (str(workspace_id) if workspace_id else "control").encode(),
            month.isoformat().encode(),
            action.encode(),
        ]
    )


def generate_keypair() -> tuple[bytes, bytes]:
    """(raw private key, raw public key), 32 bytes each."""
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return raw_private, raw_public


def seal(  # noqa: PLR0913 - the binding is five named values
    payload: Mapping[str, Any],
    public_key: bytes,
    *,
    org_id: UUID | str,
    workspace_id: UUID | str | None,
    month: date,
    action: str,
) -> bytes:
    body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str).encode()
    return SUITE.encrypt(
        body,
        X25519PublicKey.from_public_bytes(public_key),
        info=_info(org_id, workspace_id, month, action),
    )


def unseal(  # noqa: PLR0913 - the binding is five named values
    sealed: bytes,
    private_key: bytes,
    *,
    org_id: UUID | str,
    workspace_id: UUID | str | None,
    month: date,
    action: str,
) -> dict[str, Any]:
    body = SUITE.decrypt(
        sealed,
        X25519PrivateKey.from_private_bytes(private_key),
        info=_info(org_id, workspace_id, month, action),
    )
    return json.loads(body)
