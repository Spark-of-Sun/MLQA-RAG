"""Tests for vectorstore client implementations and tenant isolation."""

from __future__ import annotations

import uuid

import pytest
from lmqa_vectorstore import (
    LocalVectorStoreClient,
    QdrantVectorStoreClient,
    VectorPoint,
    VectorQuery,
    compute_deterministic_embedding,
    cosine_similarity,
)


@pytest.mark.stage0
@pytest.mark.unit
def test_embedding_and_similarity() -> None:
    """Verify deterministic embedding dimensions, normalization, and similarity."""
    v1 = compute_deterministic_embedding("confidential merger agreement article 1", dim=384)
    v2 = compute_deterministic_embedding("confidential merger agreement article 1", dim=384)
    v3 = compute_deterministic_embedding("unrelated medical clinical trial report", dim=384)

    assert len(v1) == 384
    # Identical text produces identical embeddings
    assert v1 == v2
    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0

    # Different texts have lower similarity
    sim_diff = cosine_similarity(v1, v3)
    assert sim_diff < 0.95


@pytest.mark.stage0
@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_vectorstore_isolation() -> None:
    """Verify local vectorstore enforces strict tenant and workspace boundaries."""
    store = LocalVectorStoreClient()
    collection = "test_chunks"
    await store.ensure_collection(collection)

    org_a = uuid.uuid4()
    ws_a = uuid.uuid4()
    doc_a = uuid.uuid4()

    org_b = uuid.uuid4()
    ws_b = uuid.uuid4()

    point_1 = VectorPoint(
        id=uuid.uuid4(),
        vector=compute_deterministic_embedding("payment terms section 4"),
        payload={"org_id": str(org_a), "workspace_id": str(ws_a), "doc_id": str(doc_a)},
    )

    # Upsert with matching tenant parameters succeeds
    await store.upsert(collection, [point_1], org_id=org_a, workspace_id=ws_a)

    # Upsert with mismatched tenant parameters fails
    point_invalid = VectorPoint(
        id=uuid.uuid4(),
        vector=compute_deterministic_embedding("invalid leak attempt"),
        payload={"org_id": str(org_a), "workspace_id": str(ws_a), "doc_id": str(doc_a)},
    )
    with pytest.raises(ValueError, match="Vector point payload isolation mismatch"):
        await store.upsert(collection, [point_invalid], org_id=org_b, workspace_id=ws_b)

    # Search from Org A finds point_1
    query_a = VectorQuery(
        query_vector=compute_deterministic_embedding("payment terms"),
        org_id=org_a,
        workspace_id=ws_a,
    )
    results_a = await store.search(collection, query_a)
    assert len(results_a) == 1
    assert results_a[0].id == point_1.id

    # Search from Org B finds NOTHING (Isolation barrier)
    query_b = VectorQuery(
        query_vector=compute_deterministic_embedding("payment terms"),
        org_id=org_b,
        workspace_id=ws_b,
    )
    results_b = await store.search(collection, query_b)
    assert len(results_b) == 0

    # Delete document removes point
    await store.delete_document(collection, org_id=org_a, workspace_id=ws_a, doc_id=doc_a)
    results_after_del = await store.search(collection, query_a)
    assert len(results_after_del) == 0


@pytest.mark.stage0
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_qdrant_isolation() -> None:
    """Verify live Qdrant container enforces tenant payload isolation."""
    client = QdrantVectorStoreClient(base_url="http://127.0.0.1:6333")
    collection = f"test_coll_{uuid.uuid4().hex[:8]}"

    await client.ensure_collection(collection, vector_size=384)

    org_1 = uuid.uuid4()
    ws_1 = uuid.uuid4()
    doc_1 = uuid.uuid4()

    org_2 = uuid.uuid4()
    ws_2 = uuid.uuid4()

    pt = VectorPoint(
        id=uuid.uuid4(),
        vector=compute_deterministic_embedding("severability and governing law clause"),
        payload={"org_id": str(org_1), "workspace_id": str(ws_1), "doc_id": str(doc_1)},
    )

    await client.upsert(collection, [pt], org_id=org_1, workspace_id=ws_1)

    # Search under tenant 1: finds point
    query_1 = VectorQuery(
        query_vector=compute_deterministic_embedding("governing law"),
        org_id=org_1,
        workspace_id=ws_1,
    )
    res1 = await client.search(collection, query_1)
    assert len(res1) >= 1
    assert res1[0].id == pt.id

    # Search under tenant 2: must return 0 results
    query_2 = VectorQuery(
        query_vector=compute_deterministic_embedding("governing law"),
        org_id=org_2,
        workspace_id=ws_2,
    )
    res2 = await client.search(collection, query_2)
    assert len(res2) == 0

    # Clean up test doc
    await client.delete_document(collection, org_id=org_1, workspace_id=ws_1, doc_id=doc_1)
    res_deleted = await client.search(collection, query_1)
    assert len(res_deleted) == 0
