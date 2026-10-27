"""Live integration tests for retrieval engine PostgreSQL RLS cross-check.

Master System Design §10.5 & Gate G5.4.
"""

from __future__ import annotations

import uuid

import pytest
from lmqa_vectorstore import QdrantVectorStoreClient, VectorPoint, compute_deterministic_embedding
from retrieval.search import RetrievalConfig, RetrievalEngine

from tools.load_corpus.main import (
    DEFAULT_TENANT_ALPHA_ORG,
    DEFAULT_TENANT_ALPHA_WS,
    DEFAULT_TENANT_BETA_ORG,
    DEFAULT_TENANT_BETA_WS,
)


@pytest.mark.stage5
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_retrieval_postgres_cross_check_authorized() -> None:
    """Verify that chunks authorized by PostgreSQL RLS are returned with verified text."""
    engine = RetrievalEngine()
    record = await engine.search(
        org_id=DEFAULT_TENANT_ALPHA_ORG,
        workspace_id=DEFAULT_TENANT_ALPHA_WS,
        user_id="auth0|user_alpha",
        query="distributor agreement and termination terms",
        limit=5,
    )

    assert record.org_id == DEFAULT_TENANT_ALPHA_ORG
    assert record.workspace_id == DEFAULT_TENANT_ALPHA_WS
    assert len(record.aliases) > 0

    # Chunks are validated by PostgreSQL under RLS
    for alias in record.aliases:
        assert not alias.dropped
        assert alias.drop_reason is None
        assert len(alias.text) > 0
        assert len(alias.content_hash) == 64


@pytest.mark.stage5
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_retrieval_postgres_cross_check_blocks_leak() -> None:
    """Verify defense-in-depth: if vectorstore returns a foreign chunk, PostgreSQL RLS drops it."""
    test_collection = f"leak_test_{uuid.uuid4().hex[:8]}"
    qdrant = QdrantVectorStoreClient()
    await qdrant.ensure_collection(test_collection, 384)

    # Insert a fake vector in Tenant Beta's namespace pointing to a random/unauthorized chunk ID
    fake_chunk_id = uuid.uuid4()
    pt = VectorPoint(
        id=fake_chunk_id,
        vector=compute_deterministic_embedding("Confidential secret leak query"),
        payload={
            "org_id": str(DEFAULT_TENANT_BETA_ORG),
            "workspace_id": str(DEFAULT_TENANT_BETA_WS),
            "title": "Maliciously Injected Document",
            "page": "1",
            "section": "Exfiltration",
        },
    )
    await qdrant.upsert(
        test_collection,
        [pt],
        org_id=DEFAULT_TENANT_BETA_ORG,
        workspace_id=DEFAULT_TENANT_BETA_WS,
    )

    cfg = RetrievalConfig(collection_name=test_collection)
    engine = RetrievalEngine(config=cfg, vector_client=qdrant)

    # Search in Tenant Beta
    record = await engine.search(
        org_id=DEFAULT_TENANT_BETA_ORG,
        workspace_id=DEFAULT_TENANT_BETA_WS,
        user_id="auth0|user_beta",
        query="Confidential secret leak query",
        limit=5,
    )

    assert len(record.aliases) == 1
    leaked_alias = record.aliases[0]
    # PostgreSQL RLS denied the chunk because it doesn't exist under Tenant Beta!
    assert leaked_alias.dropped is True
    assert leaked_alias.drop_reason == "rls_denied"
    assert leaked_alias.text == ""
    assert leaked_alias.content_hash == ""
