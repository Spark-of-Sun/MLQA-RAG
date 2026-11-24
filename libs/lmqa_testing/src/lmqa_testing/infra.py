"""Probes of the real local infrastructure (blueprint 4.5, 4.6, G0.4, G0.9). Used by `make doctor` and the gates.

Every probe talks to the running server with the credentials its owner would use; nothing is simulated. Secrets are
read from settings and never returned or printed.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import time
from dataclasses import dataclass, field
from typing import Any

import boto3
import httpx
import valkey
from botocore.config import Config
from botocore.exceptions import ClientError

from lmqa_db import connect_role as connect
from lmqa_models.envfile import ROOT
from lmqa_models.infra import OBJECT_STORE_BUCKET, InfraSettings, load_infra_settings
from lmqa_models.settings import Settings, load_settings

TIMEOUT = 5.0


def postgres_versions(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or load_settings()
    with connect(settings, "lmqa_owner", connect_timeout=5) as conn:
        server = conn.execute("show server_version").fetchone()
        vector = conn.execute(
            "select extversion from pg_extension where extname = 'vector'"
        ).fetchone()
    return {
        "postgresql": str(server[0]).split()[0] if server else "",
        "pgvector": str(vector[0]) if vector else "",
    }


def qdrant_version(infra: InfraSettings | None = None) -> str:
    infra = infra or load_infra_settings()
    resp = httpx.get(
        infra.qdrant_url, headers={"api-key": infra.require("QDRANT_KEY_RO")}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    return str(resp.json()["version"])


def valkey_client(user: str, infra: InfraSettings | None = None, **kwargs: Any) -> valkey.Valkey:
    infra = infra or load_infra_settings()
    return valkey.Valkey.from_url(
        infra.valkey_url,
        username=user,
        password=infra.valkey_password(user),
        socket_timeout=TIMEOUT,
        **kwargs,
    )


def valkey_version(infra: InfraSettings | None = None) -> str:
    with valkey_client("doctor", infra) as client:
        info = client.info("server")
    return str(info["valkey_version"])


def openbao_version(infra: InfraSettings | None = None) -> str:
    infra = infra or load_infra_settings()
    resp = httpx.get(f"{infra.openbao_addr}/v1/sys/health", timeout=TIMEOUT)
    resp.raise_for_status()
    return str(resp.json()["version"])


def server_versions() -> dict[str, str]:
    """What each running server reports; compared with the Servers section of docs/versions.md (G0.4)."""
    infra = load_infra_settings()
    return {
        **postgres_versions(),
        "qdrant": qdrant_version(infra),
        "valkey": valkey_version(infra),
        "openbao": openbao_version(infra),
    }


# --- object store capability probe (G0.4: versioning, presigned URLs, multipart, checksum headers) -------------


def s3_client(role: str, infra: InfraSettings | None = None) -> Any:
    infra = infra or load_infra_settings()
    access, secret = infra.object_store_credentials(role)
    return boto3.client(
        "s3",
        endpoint_url=infra.object_store_endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=infra.object_store_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1},
            connect_timeout=TIMEOUT,
            read_timeout=30,
            # Send checksums only when asked, so the probe controls exactly which header each request carries.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


@dataclass
class Capabilities:
    versioning: bool = False
    presigned_put_get: bool = False
    presigned_expiry_enforced: bool = False
    multipart: bool = False
    checksum_accepted: bool = False
    checksum_mismatch_rejected: bool = False
    scoped_credentials: bool = False
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def all_ok(self) -> bool:
        return all(v for k, v in vars(self).items() if k != "errors")


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", "unknown"))


def ensure_bucket(client: Any, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})


def _empty_and_delete(client: Any, bucket: str) -> None:
    try:
        pages = client.get_paginator("list_object_versions").paginate(Bucket=bucket)
        for page in pages:
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                client.delete_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
        for up in client.list_multipart_uploads(Bucket=bucket).get("Uploads", []):
            client.abort_multipart_upload(Bucket=bucket, Key=up["Key"], UploadId=up["UploadId"])
        client.delete_bucket(Bucket=bucket)
    except ClientError:
        pass


def object_store_capabilities(infra: InfraSettings | None = None) -> Capabilities:  # noqa: PLR0915 - one linear flow; splitting it is a DEV-33 follow-up
    """Exercise the store the way ingestion will use it, on a throwaway bucket (deleted afterwards)."""
    infra = infra or load_infra_settings()
    admin = s3_client("admin", infra)
    caps = Capabilities()
    bucket = f"lmqa-probe-{secrets.token_hex(4)}"
    # Real files, never generated text (rule R1): this repository's README and its version ledger.
    body_a = (ROOT / "README.md").read_bytes()
    body_b = (ROOT / "pyproject.toml").read_bytes()
    admin.create_bucket(Bucket=bucket)
    try:
        try:
            admin.put_bucket_versioning(
                Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
            )
            v1 = admin.put_object(Bucket=bucket, Key="v", Body=body_a)["VersionId"]
            admin.put_object(Bucket=bucket, Key="v", Body=body_b)
            versions = admin.list_object_versions(Bucket=bucket, Prefix="v").get("Versions", [])
            old = admin.get_object(Bucket=bucket, Key="v", VersionId=v1)["Body"].read()
            caps.versioning = len(versions) == 2 and old == body_a
        except ClientError as exc:
            caps.errors["versioning"] = _code(exc)

        try:
            put_url = admin.generate_presigned_url(
                "put_object", Params={"Bucket": bucket, "Key": "p"}, ExpiresIn=60
            )
            get_url = admin.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": "p"}, ExpiresIn=60
            )
            put = httpx.put(put_url, content=body_a, timeout=TIMEOUT)
            got = httpx.get(get_url, timeout=TIMEOUT)
            caps.presigned_put_get = put.status_code == 200 and got.content == body_a
            short = admin.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": "p"}, ExpiresIn=1
            )
            time.sleep(2.2)
            caps.presigned_expiry_enforced = httpx.get(short, timeout=TIMEOUT).status_code == 403
        except (ClientError, httpx.HTTPError) as exc:
            caps.errors["presigned"] = type(exc).__name__

        try:
            part1 = body_a * (
                5 * 1024 * 1024 // len(body_a) + 1
            )  # parts other than the last must be >= 5 MiB
            part2 = body_b
            up = admin.create_multipart_upload(Bucket=bucket, Key="m")
            e1 = admin.upload_part(
                Bucket=bucket, Key="m", UploadId=up["UploadId"], PartNumber=1, Body=part1
            )["ETag"]
            e2 = admin.upload_part(
                Bucket=bucket, Key="m", UploadId=up["UploadId"], PartNumber=2, Body=part2
            )["ETag"]
            admin.complete_multipart_upload(
                Bucket=bucket,
                Key="m",
                UploadId=up["UploadId"],
                MultipartUpload={
                    "Parts": [{"PartNumber": 1, "ETag": e1}, {"PartNumber": 2, "ETag": e2}]
                },
            )
            caps.multipart = (
                admin.get_object(Bucket=bucket, Key="m")["Body"].read() == part1 + part2
            )
        except ClientError as exc:
            caps.errors["multipart"] = _code(exc)

        good = base64.b64encode(hashlib.sha256(body_a).digest()).decode()
        bad = base64.b64encode(hashlib.sha256(body_b).digest()).decode()
        try:
            admin.put_object(Bucket=bucket, Key="c", Body=body_a, ChecksumSHA256=good)
            caps.checksum_accepted = True
        except ClientError as exc:
            caps.errors["checksum"] = _code(exc)
        try:
            admin.put_object(Bucket=bucket, Key="c2", Body=body_a, ChecksumSHA256=bad)
            caps.errors["checksum_mismatch"] = "accepted a wrong SHA-256"
        except ClientError:
            caps.checksum_mismatch_rejected = True

        ingestion = s3_client("ingestion", infra)
        try:
            ensure_bucket(admin, OBJECT_STORE_BUCKET)
            ingestion.put_object(Bucket=OBJECT_STORE_BUCKET, Key="probe/scope", Body=body_a)
            in_scope = True
            ingestion.delete_object(Bucket=OBJECT_STORE_BUCKET, Key="probe/scope")
        except ClientError as exc:
            in_scope = False
            caps.errors["scope_own_bucket"] = _code(exc)
        try:
            ingestion.put_object(Bucket=bucket, Key="outside", Body=body_a)
            caps.errors["scope_other_bucket"] = "ingestion wrote outside its bucket"
            out_denied = False
        except ClientError:
            out_denied = True
        caps.scoped_credentials = in_scope and out_denied
    finally:
        _empty_and_delete(admin, bucket)
    return caps


# --- OpenBao Transit (local key provider) ----------------------------------------------------------------------


def openbao_request(
    method: str, path: str, infra: InfraSettings | None = None, **kwargs: Any
) -> httpx.Response:
    infra = infra or load_infra_settings()
    headers = {"X-Vault-Token": infra.require("OPENBAO_TOKEN")}
    return httpx.request(
        method, f"{infra.openbao_addr}/v1/{path}", headers=headers, timeout=TIMEOUT, **kwargs
    )


def ensure_transit(infra: InfraSettings | None = None) -> None:
    mounts = openbao_request("GET", "sys/mounts", infra)
    mounts.raise_for_status()
    if "transit/" not in mounts.json().get("data", mounts.json()):
        openbao_request(
            "POST", "sys/mounts/transit", infra, json={"type": "transit"}
        ).raise_for_status()


# --- ClamAV ----------------------------------------------------------------------------------------------------


def clamd_command(command: bytes, infra: InfraSettings | None = None) -> str:
    """Send one zINSTREAM-free command (PING, VERSION) to clamd and return its reply."""
    infra = infra or load_infra_settings()
    with socket.create_connection((infra.clamav_host, infra.clamav_port), timeout=TIMEOUT) as sock:
        sock.sendall(b"z" + command + b"\0")
        chunks = []
        while chunk := sock.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks).rstrip(b"\0").decode()
