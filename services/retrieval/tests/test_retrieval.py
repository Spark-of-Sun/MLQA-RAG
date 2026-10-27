"""Unit tests for retrieval engine."""

from __future__ import annotations

import uuid

import pytest
from lmqa_vectorstore import LocalVectorStoreClient, VectorPoint, compute_deterministic_embedding
from retrieval.search import RetrievalEngine


@pytest.mark.stage0
@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieval_engine_search_isolation() -> None:
    """Verify retrieval engine enforces tenant and workspace boundaries."""
    local_store = LocalVectorStoreClient()
    engine = RetrievalEngine(vector_client=local_store)

    org1 = uuid.uuid4()
    ws1 = uuid.uuid4()
    org2 = uuid.uuid4()
    ws2 = uuid.uuid4()

    point1 = VectorPoint(
        id=uuid.uuid4(),
        vector=compute_deterministic_embedding("Arbitration clause governs all disputes."),
        payload={
            "org_id": str(org1),
            "workspace_id": str(ws1),
            "text": "Arbitration clause governs all disputes.",
            "title": "Master Services Agreement",
            "page": "12",
            "section": "Dispute Resolution",
            "content_hash": "abc123hash",
        },
    )
    point2 = VectorPoint(
        id=uuid.uuid4(),
        vector=compute_deterministic_embedding("Confidential information shall be kept secret."),
        payload={
            "org_id": str(org2),
            "workspace_id": str(ws2),
            "text": "Confidential information shall be kept secret.",
            "title": "Non-Disclosure Agreement",
            "page": "3",
            "section": "Confidentiality",
            "content_hash": "def456hash",
        },
    )

    await local_store.upsert("document_chunks", [point1], org1, ws1)
    await local_store.upsert("document_chunks", [point2], org2, ws2)

    # Search in org1/ws1
    record = await engine.search(org1, ws1, "auth0|user1", "Arbitration clause", limit=5)
    assert record.org_id == org1
    assert record.workspace_id == ws1
    assert len(record.aliases) == 1
    assert record.aliases[0].alias == "chunk_1"
    assert "Arbitration" in record.aliases[0].text
    assert record.aliases[0].doc_name == "Master Services Agreement"

    # Search in org2/ws2 verifies org2 only sees its own documents, never org1
    record2 = await engine.search(org2, ws2, "auth0|user2", "Arbitration clause", limit=5)
    assert len(record2.aliases) == 1
    assert record2.aliases[0].doc_name == "Non-Disclosure Agreement"
    assert "Arbitration" not in record2.aliases[0].text

    # Search in org3/ws3 with zero documents returns empty result
    org3 = uuid.uuid4()
    ws3 = uuid.uuid4()
    record3 = await engine.search(org3, ws3, "auth0|user3", "Arbitration clause", limit=5)
    assert len(record3.aliases) == 0
