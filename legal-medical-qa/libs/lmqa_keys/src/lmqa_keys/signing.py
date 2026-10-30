"""Trust-root signing for internal certificates (doc 9.1, 12.1).

The trust root is an asymmetric key (ECC P-256) that can only sign and verify. It signs
short-lived *signer certificates*, never individual requests, so KMS is called about once per
instance per hour (DEF-26). Two real adapters: OpenBao Transit locally, AWS KMS in production.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Protocol, runtime_checkable

import boto3
import httpx

from lmqa_keys.provider import KeyProviderError


@runtime_checkable
class TrustRoot(Protocol):
    """A key that signs certificates. Verification is done locally with ``public_key_pem``."""

    async def sign(self, message: bytes) -> bytes:
        """Return an ASN.1 DER ECDSA-SHA256 signature over ``message``."""
        ...

    async def public_key_pem(self) -> bytes:
        """Return the verification key as PEM."""
        ...


class OpenBaoTrustRoot:
    """ECDSA P-256 key in OpenBao Transit."""

    def __init__(self, addr: str, token: str, key_name: str, *, mount: str = "transit") -> None:
        """Connect; the key must exist (see ``create``)."""
        self._name, self._mount = key_name, mount
        self._client = httpx.AsyncClient(
            base_url=addr.rstrip("/"), headers={"X-Vault-Token": token}, timeout=10.0
        )

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def create(self) -> None:
        """Create the signing key if it does not exist yet."""
        response = await self._client.post(
            f"/v1/{self._mount}/keys/{self._name}", json={"type": "ecdsa-p256"}
        )
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"cannot create trust root: {response.status_code}"
            raise KeyProviderError(msg)

    async def sign(self, message: bytes) -> bytes:
        """Sign with the Transit ``sign`` endpoint, DER-encoded."""
        response = await self._client.post(
            f"/v1/{self._mount}/sign/{self._name}/sha2-256",
            json={"input": base64.b64encode(message).decode(), "marshaling_algorithm": "asn1"},
        )
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"trust root sign failed: {response.status_code}"
            raise KeyProviderError(msg)
        signature = str(response.json()["data"]["signature"])
        return base64.b64decode(signature.rsplit(":", 1)[-1])

    def public_key_pem_sync(self) -> bytes:
        """The latest version's public key, fetched synchronously (service start-up)."""
        response = httpx.get(
            f"{self._client.base_url}/v1/{self._mount}/keys/{self._name}",
            headers={"X-Vault-Token": self._client.headers["X-Vault-Token"]},
            timeout=10.0,
        )
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"cannot read trust root: {response.status_code}"
            raise KeyProviderError(msg)
        keys: dict[str, Any] = response.json()["data"]["keys"]
        return str(keys[max(keys, key=int)]["public_key"]).encode()

    async def public_key_pem(self) -> bytes:
        """The latest version's public key."""
        response = await self._client.get(f"/v1/{self._mount}/keys/{self._name}")
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"cannot read trust root: {response.status_code}"
            raise KeyProviderError(msg)
        keys: dict[str, Any] = response.json()["data"]["keys"]
        latest = max(keys, key=int)
        return str(keys[latest]["public_key"]).encode()


class AwsKmsTrustRoot:
    """ECC_NIST_P256 SIGN_VERIFY key in AWS KMS (rotated every 90 days with overlap)."""

    def __init__(self, region: str, key_id: str) -> None:
        """Create the signer. Credentials come from the environment or an assumed role."""
        self._kms: Any = boto3.client("kms", region_name=region)  # pyright: ignore[reportUnknownMemberType]
        self._key_id = key_id

    async def sign(self, message: bytes) -> bytes:
        """Sign with KMS (ECDSA_SHA_256 over the raw message)."""
        out = await asyncio.to_thread(
            self._kms.sign,
            KeyId=self._key_id,
            Message=message,
            MessageType="RAW",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return bytes(out["Signature"])

    def public_key_pem_sync(self) -> bytes:
        """Fetch the DER public key and return it as PEM, synchronously (service start-up)."""
        out = self._kms.get_public_key(KeyId=self._key_id)
        der = bytes(out["PublicKey"])
        body = base64.encodebytes(der).decode().replace("\n", "")
        lines = [body[i : i + 64] for i in range(0, len(body), 64)]
        return (
            "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----\n"
        ).encode()

    async def public_key_pem(self) -> bytes:
        """Fetch the DER public key and return it as PEM."""
        return await asyncio.to_thread(self.public_key_pem_sync)
