"""S3-compatible object store with application-level encryption (blueprint 10.5, 12.3, D19, G4.1, G4.11).

The same code runs against SeaweedFS locally and S3 in production: objects are encrypted by the application before
upload (lmqa_keys.envelope chunked AES-256-GCM under the document key), so the store never holds plaintext and SSE
is optional. Uploads from browsers use presigned PUT URLs constrained to one key under the workspace prefix, a
content length, a content type and a required SHA-256 checksum, valid for 60 seconds; they land in `quarantine/`
and are moved to the final prefix only after scanning and parsing.

Keys are built from database UUIDs only (`org_<id>/ws_<id>/doc_<id>/v<n>/original.enc`), never from client input.
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from botocore.config import Config
from botocore.exceptions import ClientError

from lmqa_keys.envelope import Binding, decrypt_stream, encrypt_stream

PRESIGN_SECONDS = 60
PART = 8 * 1024 * 1024


class ObjectStoreError(RuntimeError):
    pass


def _uuid(v: object) -> str:
    return str(UUID(str(v)))


def final_key(org_id: object, workspace_id: object, document_id: object, version: int = 1) -> str:
    return f"org_{_uuid(org_id)}/ws_{_uuid(workspace_id)}/doc_{_uuid(document_id)}/v{int(version)}/original.enc"


def quarantine_key(
    org_id: object, workspace_id: object, document_id: object, version: int = 1
) -> str:
    return f"quarantine/org_{_uuid(org_id)}/ws_{_uuid(workspace_id)}/doc_{_uuid(document_id)}/v{int(version)}"


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    key: str
    headers: dict[str, str]
    expires_in: int


class S3ObjectStore:
    def __init__(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        *,
        endpoint: str | None,
        access_key: str | None,
        secret_key: str | None,
        bucket: str,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                    retries={"max_attempts": 3},
                ),
            )
        self._s3 = client
        self.bucket = bucket

    # --- presigned browser uploads (G4.1) -----------------------------------------------------------------

    def presign_upload(
        self, key: str, *, size: int, content_type: str, sha256_hex: str
    ) -> PresignedUpload:
        if not key.startswith("quarantine/"):
            raise ObjectStoreError("browser uploads go to quarantine only")
        checksum = base64.b64encode(bytes.fromhex(sha256_hex)).decode()
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentLength": size,
            "ContentType": content_type,
            "ChecksumSHA256": checksum,
        }
        url = self._s3.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=PRESIGN_SECONDS
        )
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(size),
            "x-amz-checksum-sha256": checksum,
        }
        return PresignedUpload(url, key, headers, PRESIGN_SECONDS)

    def read_quarantine(self, key: str, *, expected_sha256: str, max_bytes: int) -> bytes:
        try:
            head = self._s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise ObjectStoreError("upload not found") from exc
        if int(head["ContentLength"]) > max_bytes:
            raise ObjectStoreError("upload too large")
        data = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ObjectStoreError("checksum mismatch")
        return data

    def delete_quarantine(self, key: str) -> None:
        self._delete_all_versions(key)

    # --- encrypted originals ------------------------------------------------------------------------------

    def put_encrypted(
        self, key: str, data: bytes, *, doc_key: bytes, binding: Binding, key_version: int = 1
    ) -> dict[str, str]:
        body = b"".join(encrypt_stream(doc_key, key_version, io.BytesIO(data), binding))
        digest = hashlib.sha256(body).hexdigest()
        out = self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
            ContentType="application/octet-stream",
        )
        return {"version_id": str(out.get("VersionId") or ""), "ciphertext_sha256": digest}

    def get_decrypted(self, key: str, *, doc_key: bytes, binding: Binding) -> bytes:
        body = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"]
        return b"".join(decrypt_stream(doc_key, _iter_body(body), binding))

    def delete_object(self, key: str) -> int:
        """Delete every version of `key` (crypto-erase already made them unreadable; this removes the bytes)."""
        return self._delete_all_versions(key)

    def _delete_all_versions(self, key: str) -> int:
        n = 0
        pages = self._s3.get_paginator("list_object_versions").paginate(
            Bucket=self.bucket, Prefix=key
        )
        for page in pages:
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                if item["Key"] == key:
                    self._s3.delete_object(Bucket=self.bucket, Key=key, VersionId=item["VersionId"])
                    n += 1
        return n

    def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        for page in self._s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return keys


def _iter_body(body: Any) -> Iterator[bytes]:
    while chunk := body.read(1024 * 1024):
        yield chunk
