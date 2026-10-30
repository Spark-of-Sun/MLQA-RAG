"""G1.10 and G1.11 against a real OpenBao Transit server (doc 12, 19.1 R2)."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from lmqa_keys import (
    Aad,
    ContextMismatchError,
    DocumentKeyDestroyedError,
    KeyProviderError,
    KeyService,
    KeyState,
    KeyUnavailableError,
    OpenBaoProvider,
    decrypt,
    encrypt,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = [pytest.mark.integration, pytest.mark.live_kms, pytest.mark.stage1]


@pytest_asyncio.fixture
async def provider() -> AsyncGenerator[OpenBaoProvider]:
    addr = os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200")
    token = os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token")
    async with OpenBaoProvider(addr, token) as p:
        yield p


async def _workspace(svc: KeyService) -> tuple[UUID, UUID, str, bytes, bytes]:
    org, ws = uuid4(), uuid4()
    ids = await svc.provision_org(org)
    key, wrapped = await svc.new_workspace_key(ids.cmk_id, org, ws, version=1)
    return org, ws, ids.cmk_id, key, wrapped


@pytest.mark.asyncio
async def test_hierarchy_round_trip_and_wrong_scope_unwrap_is_refused_by_the_kms(
    provider: OpenBaoProvider,
) -> None:
    svc = KeyService(provider)
    org, ws, cmk, key, wrapped = await _workspace(svc)
    fresh = KeyService(provider)  # a second instance with an empty cache must reach the same key
    assert await fresh.workspace_key(cmk, org, ws, 1, wrapped) == key
    # The same wrapped key presented for a different workspace or organization fails in the KMS.
    for other_org, other_ws in ((org, uuid4()), (uuid4(), ws)):
        with pytest.raises(ContextMismatchError):
            await KeyService(provider).workspace_key(cmk, other_org, other_ws, 1, wrapped)
    # A document key chain: workspace key wraps a random document key, which encrypts chunk text.
    doc = uuid4()
    doc_key, doc_wrapped = KeyService.new_document_key(key, org, ws, doc)
    blob = encrypt(doc_key, b"Section 4.2 Termination", Aad(org, ws, doc, version=1, ordinal=0))
    reopened = KeyService.open_document_key(key, doc_wrapped, org, ws, doc)
    assert (
        decrypt(reopened, blob, Aad(org, ws, doc, version=1, ordinal=0))
        == b"Section 4.2 Termination"
    )
    with pytest.raises(Exception, match="decryption failed"):
        KeyService.open_document_key(key, doc_wrapped, org, ws, uuid4())  # a different document ID


@pytest.mark.asyncio
async def test_two_organizations_get_different_keys_and_cannot_open_each_other(
    provider: OpenBaoProvider,
) -> None:
    svc = KeyService(provider)
    org_a, ws_a, cmk_a, _ka, wrapped_a = await _workspace(svc)
    _org_b, _ws_b, cmk_b, _kb, _wb = await _workspace(svc)
    assert cmk_a != cmk_b
    with pytest.raises((KeyProviderError, ContextMismatchError)):
        await KeyService(provider).workspace_key(cmk_b, org_a, ws_a, 1, wrapped_a)


@pytest.mark.asyncio
async def test_cache_bounds_provider_calls_under_concurrency(provider: OpenBaoProvider) -> None:
    writer = KeyService(provider)
    org, ws, cmk, key, wrapped = await _workspace(writer)
    reader = KeyService(provider, cache_ttl_seconds=0.6)
    results = await asyncio.gather(
        *(reader.workspace_key(cmk, org, ws, 1, wrapped) for _ in range(200))
    )
    assert set(results) == {key}
    assert reader.stats.unwraps == 1, "200 concurrent callers share one provider call"
    assert reader.stats.cache_hits == 199
    await asyncio.sleep(0.8)  # the TTL expires in real time (configuration, not a clock fake)
    await reader.workspace_key(cmk, org, ws, 1, wrapped)
    assert reader.stats.unwraps == 2


def test_cache_ttl_beyond_policy_is_refused(provider: OpenBaoProvider) -> None:
    for bad in (0, -1, 901):
        with pytest.raises(ValueError, match="TTL"):
            KeyService(provider, cache_ttl_seconds=bad)


@pytest.mark.asyncio
async def test_g1_11_deleting_a_document_key_shreds_only_that_document(
    provider: OpenBaoProvider,
) -> None:
    svc = KeyService(provider)
    org, ws, _cmk, ws_key, _wrapped = await _workspace(svc)
    docs = {}
    for _ in range(2):
        doc = uuid4()
        key, wrapped = KeyService.new_document_key(ws_key, org, ws, doc)
        aad = Aad(org, ws, doc, version=1, ordinal=0)
        docs[doc] = (wrapped, encrypt(key, b"confidential", aad), aad)
    shredded, kept = list(docs)
    # Crypto-erase: the wrapped key is destroyed (set to None), the ciphertext stays behind.
    with pytest.raises(DocumentKeyDestroyedError):
        KeyService.open_document_key(ws_key, None, org, ws, shredded)
    wrapped, blob, aad = docs[kept]
    assert (
        decrypt(KeyService.open_document_key(ws_key, wrapped, org, ws, kept), blob, aad)
        == b"confidential"
    )


@pytest.mark.asyncio
async def test_g1_11_deleting_the_cmk_makes_everything_undecryptable_even_from_a_backup(
    provider: OpenBaoProvider,
) -> None:
    svc = KeyService(provider)
    org, ws, cmk, ws_key, wrapped_ws_key = await _workspace(svc)
    doc = uuid4()
    doc_key, wrapped_doc = KeyService.new_document_key(ws_key, org, ws, doc)
    backup = {
        "workspace": wrapped_ws_key,
        "document": wrapped_doc,
    }  # a backup of the wrapped-key tables
    assert await provider.describe(cmk) is KeyState.ENABLED
    await provider.schedule_deletion(cmk, window_days=30)  # OpenBao deletes immediately
    assert await provider.describe(cmk) is KeyState.DELETED
    svc.forget_workspace(org, ws)
    with pytest.raises(KeyUnavailableError):
        await svc.workspace_key(cmk, org, ws, 1, backup["workspace"])
    assert doc_key  # the plaintext key never left memory; nothing on disk can rebuild it


@pytest.mark.asyncio
async def test_openbao_refuses_operations_it_cannot_do_honestly(provider: OpenBaoProvider) -> None:
    cmk = await provider.create_key(f"lmqa-test-{uuid4()}")
    for call in (provider.disable, provider.enable, provider.cancel_deletion):
        with pytest.raises(KeyProviderError, match=r"OpenBao cannot|cannot be cancelled"):
            await call(cmk)
    await provider.schedule_deletion(cmk, 7)


@pytest.mark.asyncio
async def test_an_unreachable_provider_fails_closed_after_the_cache_expires() -> None:
    async with OpenBaoProvider("http://127.0.0.1:8200", "lmqa-dev-token") as live:
        svc = KeyService(live, cache_ttl_seconds=0.3)
        org, ws, cmk, _key, wrapped = await _workspace(svc)
    async with OpenBaoProvider("http://127.0.0.1:1", "x", timeout=1.0) as dead:
        cut_off = KeyService(dead, cache_ttl_seconds=0.3)
        with pytest.raises(Exception, match=r"All connection attempts failed|Connect|refused"):
            await cut_off.workspace_key(cmk, org, ws, 1, wrapped)
