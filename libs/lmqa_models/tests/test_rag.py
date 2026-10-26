"""Tests for RAG models and retrieval ledger."""

from uuid import uuid4

import pytest
from lmqa_models.rag import (
    Chunk,
    ChunkMetadata,
    CitationItem,
    RAGResponse,
    RetrievalAlias,
    RetrievalRecord,
    SentenceVerdict,
)


@pytest.mark.stage0
@pytest.mark.unit
def test_chunk_creation() -> None:
    """Verify Chunk.create computes hash and token count."""
    chunk_id = uuid4()
    org_id = uuid4()
    workspace_id = uuid4()
    meta = ChunkMetadata(
        doc_id=uuid4(),
        doc_version=1,
        ordinal=0,
        title="contract.pdf",
        page="1-2",
        section="Section 1",
    )
    chunk = Chunk.create(
        chunk_id=chunk_id,
        org_id=org_id,
        workspace_id=workspace_id,
        metadata=meta,
        text="This is a test chunk.",
    )
    assert chunk.chunk_id == chunk_id
    assert chunk.token_count == 5
    assert len(chunk.content_hash) == 64


@pytest.mark.stage0
@pytest.mark.unit
def test_retrieval_record_alias_map() -> None:
    """Verify RetrievalRecord alias_map filters dropped aliases."""
    record = RetrievalRecord(
        request_id=uuid4(),
        org_id=uuid4(),
        workspace_id=uuid4(),
        user_id="auth0|user1",
        scope_hash="hash1",
        query="what is the term?",
        aliases=[
            RetrievalAlias(
                alias="chunk_1",
                chunk_id=uuid4(),
                doc_name="doc.pdf",
                page="1",
                section="Sec 1",
                text="text",
                content_hash="h1",
                score=0.9,
            ),
            RetrievalAlias(
                alias="chunk_2",
                chunk_id=uuid4(),
                doc_name="doc.pdf",
                page="2",
                section="Sec 2",
                text="text",
                content_hash="h2",
                score=0.3,
                dropped=True,
                drop_reason="below_floor",
            ),
        ],
    )
    aliases = record.alias_map()
    assert "chunk_1" in aliases
    assert "chunk_2" not in aliases
    assert len(aliases) == 1


@pytest.mark.stage0
@pytest.mark.unit
def test_rag_response_verdicts_and_citations() -> None:
    """Verify SentenceVerdict, CitationItem, and RAGResponse creation."""
    verdict = SentenceVerdict(
        sentence="The term is 3 years [chunk_1].",
        passed=True,
        cited_aliases=["chunk_1"],
    )
    citation = CitationItem(
        alias="chunk_1",
        doc_name="lease.pdf",
        page="3",
        section="Section 2: Term",
        quote_excerpt="The initial term shall be three (3) years.",
    )
    response = RAGResponse(
        request_id=uuid4(),
        query="What is the term?",
        answer="The term is 3 years [chunk_1].",
        verdicts=[verdict],
        citations=[citation],
        refusal=False,
    )
    assert response.verdicts[0].passed is True
    assert response.citations[0].alias == "chunk_1"
    assert response.refusal is False
