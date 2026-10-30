"""Object store against a real SeaweedFS: encryption in the application, scoped keys, presign limits."""

from __future__ import annotations

import base64
import hashlib
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from lmqa_keys import DecryptionError, new_key
from lmqa_objectstore import ObjectNotFoundError, ObjectStore, object_key, quarantine_key

pytestmark = [pytest.mark.integration, pytest.mark.stage4]


@pytest_asyncio.fixture
async def store() -> ObjectStore:
    s = ObjectStore(
        os.environ.get("OBJECT_STORE_ENDPOINT", "http://127.0.0.1:8333"),
        os.environ.get("OBJECT_STORE_ACCESS_KEY", "lmqa-dev-access"),
        os.environ.get("OBJECT_STORE_SECRET_KEY", "lmqa-dev-secret"),
        "lmqa-test-shared",
        "us-east-1",  # one bucket: each bucket reserves volumes on the small local store
    )
    await s.ensure_bucket()
    return s


def test_keys_are_built_only_from_typed_identifiers() -> None:
    org, ws, doc = uuid4(), uuid4(), uuid4()
    assert object_key(org, ws, doc, 3) == f"org_{org}/ws_{ws}/doc_{doc}/v3"
    assert quarantine_key(org, ws, doc).startswith("quarantine/")
    with pytest.raises(ValueError):
        object_key("../../etc", ws, doc, 1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_round_trip_and_the_store_never_holds_plaintext(store: ObjectStore) -> None:
    org, ws, doc, key = uuid4(), uuid4(), uuid4(), new_key()
    secret = b"CONFIDENTIAL: indemnification cap is twelve months of fees. " * 5000
    path = await store.put_encrypted(
        key, org, ws, doc, 1, [secret[i : i + 7000] for i in range(0, len(secret), 7000)]
    )
    assert path == object_key(org, ws, doc, 1)
    out = await store._run("get_object", Bucket=store._bucket, Key=path)
    raw = out["Body"].read()
    assert b"indemnification" not in raw
    assert b"CONFIDENTIAL" not in raw
    assert await store.get_decrypted(key, org, ws, doc, 1) == secret


@pytest.mark.asyncio
async def test_wrong_key_wrong_scope_and_tampering_fail(store: ObjectStore) -> None:
    org, ws, doc, key = uuid4(), uuid4(), uuid4(), new_key()
    await store.put_encrypted(key, org, ws, doc, 1, [b"payload " * 1000])
    with pytest.raises(DecryptionError):
        await store.get_decrypted(new_key(), org, ws, doc, 1)
    # Copy the ciphertext to another workspace's key path: the bound scope no longer matches.
    other_ws = uuid4()
    src = object_key(org, ws, doc, 1)
    body = (await store._run("get_object", Bucket=store._bucket, Key=src))["Body"].read()
    await store._run(
        "put_object", Bucket=store._bucket, Key=object_key(org, other_ws, doc, 1), Body=body
    )
    with pytest.raises(DecryptionError):
        await store.get_decrypted(key, org, other_ws, doc, 1)
    tampered = bytearray(body)
    tampered[len(tampered) // 2] ^= 1
    await store._run("put_object", Bucket=store._bucket, Key=src, Body=bytes(tampered))
    with pytest.raises(DecryptionError):
        await store.get_decrypted(key, org, ws, doc, 1)
    with pytest.raises(ObjectNotFoundError):
        await store.get_decrypted(key, org, ws, uuid4(), 1)


@pytest.mark.asyncio
async def test_presigned_uploads_are_short_lived_checksum_bound_and_quarantine_only(
    store: ObjectStore,
) -> None:
    org, ws, doc = uuid4(), uuid4(), uuid4()
    body = b"a real upload"
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    for ttl in (0, 61, 3600):
        with pytest.raises(ValueError, match="60 seconds"):
            store.presign_quarantine_upload(org, ws, doc, digest, ttl)
    url = store.presign_quarantine_upload(org, ws, doc, digest, 60)
    assert quarantine_key(org, ws, doc) in url
    headers = {"x-amz-checksum-sha256": digest}
    async with httpx.AsyncClient() as client:
        bad = await client.put(url, content=b"different bytes", headers=headers)
        good = await client.put(url, content=body, headers=headers)
    assert bad.status_code >= 400
    assert good.status_code == 200
    data, sha = await store.read_quarantine(org, ws, doc)
    assert data == body
    assert sha == hashlib.sha256(body).hexdigest()
    await store.delete_quarantine(org, ws, doc)
    with pytest.raises(ObjectNotFoundError):
        await store.read_quarantine(org, ws, doc)


@pytest.mark.asyncio
async def test_deleting_a_document_removes_every_version_and_nothing_else(
    store: ObjectStore,
) -> None:
    org, ws, doc, other, key = uuid4(), uuid4(), uuid4(), uuid4(), new_key()
    for v in (1, 2):
        await store.put_encrypted(key, org, ws, doc, v, [b"x" * 100])
    await store.put_encrypted(key, org, ws, other, 1, [b"y" * 100])
    assert await store.delete_document(org, ws, doc) == 2
    assert not await store.exists(object_key(org, ws, doc, 1))
    assert await store.exists(object_key(org, ws, other, 1))
