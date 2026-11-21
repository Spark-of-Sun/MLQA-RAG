"""G0.4 capability probe for the local S3-compatible object store (doc 4.5, D19).

SeaweedFS is chosen for local use only if it passes: bucket versioning, presigned PUT with a
required checksum, multipart upload, checksum headers and prefix-scoped keys. A failure means the
alternate store is selected. Exit status 1 on any failed capability. Reads the endpoint and keys
from the environment (OBJECT_STORE_*), never from code.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import uuid

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError


def _client() -> boto3.session.Session.client:  # type: ignore[valid-type]
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("OBJECT_STORE_ENDPOINT", "http://127.0.0.1:8333"),
        aws_access_key_id=os.environ.get("OBJECT_STORE_ACCESS_KEY", "lmqa-dev-access"),
        aws_secret_access_key=os.environ.get("OBJECT_STORE_SECRET_KEY", "lmqa-dev-secret"),
        region_name=os.environ.get("OBJECT_STORE_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def main() -> int:
    s3 = _client()
    bucket = f"probe-{uuid.uuid4().hex[:10]}"
    results: dict[str, str] = {}
    s3.create_bucket(Bucket=bucket)

    def check(name: str, fn) -> None:  # noqa: ANN001
        try:
            fn()
            results[name] = "PASS"
        except (ClientError, AssertionError, httpx.HTTPError, KeyError) as exc:
            results[name] = f"FAIL: {type(exc).__name__}: {exc}"[:120]

    def versioning() -> None:
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        first = s3.put_object(Bucket=bucket, Key="v/doc", Body=b"one")["VersionId"]
        second = s3.put_object(Bucket=bucket, Key="v/doc", Body=b"two")["VersionId"]
        assert first != second
        assert s3.get_object(Bucket=bucket, Key="v/doc", VersionId=first)["Body"].read() == b"one"

    def checksum_header() -> None:
        body = b"checksummed payload"
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
        s3.put_object(Bucket=bucket, Key="c/doc", Body=body, ChecksumSHA256=digest)
        head = s3.head_object(Bucket=bucket, Key="c/doc", ChecksumMode="ENABLED")
        assert head.get("ChecksumSHA256") == digest
        try:
            s3.put_object(
                Bucket=bucket,
                Key="c/bad",
                Body=body,
                ChecksumSHA256=base64.b64encode(b"x" * 32).decode(),
            )
        except ClientError:
            return
        raise AssertionError("a wrong checksum was accepted")

    def presigned_put() -> None:
        body = b"uploaded through a presigned url"
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": "quarantine/ws1/doc1", "ChecksumSHA256": digest},
            ExpiresIn=60,
        )
        good = httpx.put(url, content=body, headers={"x-amz-checksum-sha256": digest})
        assert good.status_code == 200, good.status_code  # noqa: PLR2004
        assert s3.get_object(Bucket=bucket, Key="quarantine/ws1/doc1")["Body"].read() == body

    def multipart() -> None:
        key, part = "m/big", b"a" * (5 * 1024 * 1024)
        upload = s3.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        parts = []
        for number in (1, 2):
            etag = s3.upload_part(
                Bucket=bucket, Key=key, UploadId=upload, PartNumber=number, Body=part
            )["ETag"]
            parts.append({"ETag": etag, "PartNumber": number})
        s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload, MultipartUpload={"Parts": parts}
        )
        assert s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == 2 * len(part)

    def prefix_listing() -> None:
        for key in ("org_a/ws_1/doc/v1", "org_a/ws_2/doc/v1"):
            s3.put_object(Bucket=bucket, Key=key, Body=b"x")
        listed = s3.list_objects_v2(Bucket=bucket, Prefix="org_a/ws_1/")["Contents"]
        assert [o["Key"] for o in listed] == ["org_a/ws_1/doc/v1"]

    for name, fn in (
        ("versioning", versioning),
        ("checksum_headers", checksum_header),
        ("presigned_put", presigned_put),
        ("multipart", multipart),
        ("prefix_listing", prefix_listing),
    ):
        check(name, fn)
    for obj in s3.list_object_versions(Bucket=bucket).get("Versions", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"], VersionId=obj["VersionId"])
    s3.delete_bucket(Bucket=bucket)
    for name, outcome in results.items():
        print(f"{name:18} {outcome}")
    return 0 if all(v == "PASS" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
