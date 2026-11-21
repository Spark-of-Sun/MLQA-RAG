"""Object storage with encryption done by the application (doc 12.3).

Object keys are built here from identifiers read from database rows, never from client input
(a prefix is naming, not a control). Objects are encrypted with the per-document key before they
leave the process (AES-GCM, 1 MiB framed segments with a final marker), so plaintext never sits in
the store and local and production behave identically. Browsers never receive a URL to ciphertext;
presigned URLs exist only for uploads to the quarantine prefix, last at most 60 seconds, and bind
the SHA-256 the client must send.
"""

from __future__ import annotations

import asyncio
import hashlib
import struct
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from lmqa_keys import Aad, decrypt_stream, encrypt_stream

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

MAX_PRESIGN_SECONDS: Final = 60
_PREFIX_BYTES: Final = 8


class ObjectNotFoundError(LookupError):
    """The object does not exist."""


def _require_ids(*ids: object) -> None:
    if not all(isinstance(i, UUID) for i in ids):
        msg = "object keys are built from UUIDs read from database rows, never from client input"
        raise ValueError(msg)


def object_key(org_id: UUID, workspace_id: UUID, doc_id: UUID, version: int) -> str:
    """Final location: ``org_{id}/ws_{id}/doc_{id}/v{n}``. Built from typed IDs only."""
    _require_ids(org_id, workspace_id, doc_id)
    return f"org_{org_id}/ws_{workspace_id}/doc_{doc_id}/v{int(version)}"


def quarantine_key(org_id: UUID, workspace_id: UUID, doc_id: UUID) -> str:
    """Where an upload lands before scanning (24 hour lifecycle expiry in production)."""
    _require_ids(org_id, workspace_id, doc_id)
    return f"quarantine/org_{org_id}/ws_{workspace_id}/doc_{doc_id}"


def _frames(blob: bytes) -> Iterator[bytes]:
    yield blob[:_PREFIX_BYTES]
    offset = _PREFIX_BYTES
    while offset < len(blob):
        (length,) = struct.unpack(">I", blob[offset : offset + 4])
        yield blob[offset : offset + 4 + length]
        offset += 4 + length


class ObjectStore:
    """One bucket. The credentials are scoped to the ingestion service only (doc 9.2)."""

    def __init__(
        self, endpoint: str | None, access_key: str, secret_key: str, bucket: str, region: str
    ) -> None:
        """Create the client. ``endpoint`` is None for real AWS S3."""
        self._s3: Any = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._bucket = bucket

    async def _run(self, operation: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        try:
            result: dict[str, Any] = await asyncio.to_thread(getattr(self._s3, operation), **kwargs)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                msg = "object not found"
                raise ObjectNotFoundError(msg) from exc
            raise
        return result

    async def ensure_bucket(self) -> None:
        """Create the bucket with versioning on (idempotent)."""
        try:
            await self._run("head_bucket", Bucket=self._bucket)
        except ClientError, ObjectNotFoundError:
            await self._run("create_bucket", Bucket=self._bucket)
        await self._run(
            "put_bucket_versioning",
            Bucket=self._bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )

    def presign_quarantine_upload(
        self, org_id: UUID, ws_id: UUID, doc_id: UUID, sha256_b64: str, ttl: int = 60
    ) -> str:
        """A PUT URL to the quarantine key only, bound to the required SHA-256, valid <= 60 s."""
        if not 0 < ttl <= MAX_PRESIGN_SECONDS:
            msg = f"presigned URLs last at most {MAX_PRESIGN_SECONDS} seconds"
            raise ValueError(msg)
        return str(
            self._s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": quarantine_key(org_id, ws_id, doc_id),
                    "ChecksumSHA256": sha256_b64,
                },
                ExpiresIn=ttl,
            )
        )

    async def read_quarantine(self, org_id: UUID, ws_id: UUID, doc_id: UUID) -> tuple[bytes, str]:
        """Read an uploaded object and report the SHA-256 hex of what is actually stored."""
        out = await self._run(
            "get_object", Bucket=self._bucket, Key=quarantine_key(org_id, ws_id, doc_id)
        )
        data = bytes(await asyncio.to_thread(out["Body"].read))
        return data, hashlib.sha256(data).hexdigest()

    async def put_quarantine(self, org_id: UUID, ws_id: UUID, doc_id: UUID, data: bytes) -> str:
        """Server-side write into quarantine (small uploads and tests). Returns the SHA-256 hex."""
        digest = hashlib.sha256(data).hexdigest()
        await self._run(
            "put_object", Bucket=self._bucket, Key=quarantine_key(org_id, ws_id, doc_id), Body=data
        )
        return digest

    async def delete_quarantine(self, org_id: UUID, ws_id: UUID, doc_id: UUID) -> None:
        """Remove the plaintext upload once the encrypted copy exists, or when it is rejected."""
        await self._run(
            "delete_object", Bucket=self._bucket, Key=quarantine_key(org_id, ws_id, doc_id)
        )

    async def put_encrypted(  # noqa: PLR0913, PLR0917 - key, scope and payload all travel together
        self,
        doc_key: bytes,
        org_id: UUID,
        ws_id: UUID,
        doc_id: UUID,
        version: int,
        chunks: Iterable[bytes],
    ) -> str:
        """Encrypt under the document key and write the final object. Returns its key."""
        aad = Aad(org_id, ws_id, doc_id, version)
        blob = b"".join(await asyncio.to_thread(lambda: list(encrypt_stream(doc_key, chunks, aad))))
        key = object_key(org_id, ws_id, doc_id, version)
        await self._run("put_object", Bucket=self._bucket, Key=key, Body=blob)
        return key

    async def get_decrypted(
        self, doc_key: bytes, org_id: UUID, ws_id: UUID, doc_id: UUID, version: int
    ) -> bytes:
        """Fetch and decrypt. A wrong key, scope or any tampering raises ``DecryptionError``."""
        out = await self._run(
            "get_object", Bucket=self._bucket, Key=object_key(org_id, ws_id, doc_id, version)
        )
        blob = bytes(await asyncio.to_thread(out["Body"].read))
        aad = Aad(org_id, ws_id, doc_id, version)
        return b"".join(
            await asyncio.to_thread(lambda: list(decrypt_stream(doc_key, _frames(blob), aad)))
        )

    async def delete_document(self, org_id: UUID, ws_id: UUID, doc_id: UUID) -> int:
        """Delete every version of a document's objects (after its key was destroyed)."""
        prefix = f"org_{org_id}/ws_{ws_id}/doc_{doc_id}/"
        removed = 0
        listing = await self._run("list_object_versions", Bucket=self._bucket, Prefix=prefix)
        for entry in listing.get("Versions", []):
            await self._run(
                "delete_object", Bucket=self._bucket, Key=entry["Key"], VersionId=entry["VersionId"]
            )
            removed += 1
        return removed

    async def exists(self, key: str) -> bool:
        """True if a key exists (used by the reconciler and by deletion checks)."""
        try:
            await self._run("head_object", Bucket=self._bucket, Key=key)
        except ObjectNotFoundError, ClientError:
            return False
        return True

    async def list_prefix(self, prefix: str) -> list[str]:
        """Keys under a prefix (reconciler)."""
        out = await self._run("list_objects_v2", Bucket=self._bucket, Prefix=prefix)
        return [str(o["Key"]) for o in out.get("Contents", [])]
