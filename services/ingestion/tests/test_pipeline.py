from __future__ import annotations

from datetime import date

import pytest
from common.models import ConfidentialityTier, TenantIndustry

from app.embedding.fake_backend import FakeEmbeddingBackend
from app.ocr.fake_backend import FakeOcrBackend
from app.workers.tasks import process_document
from app.workers.vector_store import InMemoryVectorStore


def test_process_document_end_to_end_with_fakes():
    vector_store = InMemoryVectorStore()
    result = process_document(
        document_id="doc-1",
        tenant_id="t1",
        matter_or_patient_id="matter-1",
        confidentiality_tier=ConfidentialityTier.PRIVILEGED,
        industry=TenantIndustry.LEGAL,
        file_bytes=b"4.1 Confidentiality\nKeep it secret.\n4.2 Termination\n30 days notice.",
        filename="contract.pdf",
        effective_date=date(2026, 1, 1),
        ocr_backend=FakeOcrBackend(),
        embedding_backend=FakeEmbeddingBackend(dimension=8),
        vector_store=vector_store,
    )
    assert result["chunk_count"] == 2
    assert vector_store.count() == 2


def test_process_document_flags_low_confidence_pages():
    vector_store = InMemoryVectorStore()
    result = process_document(
        document_id="doc-2",
        tenant_id="t1",
        matter_or_patient_id="matter-1",
        confidentiality_tier=ConfidentialityTier.STANDARD,
        industry=TenantIndustry.MEDICAL,
        file_bytes=b"Subjective:\nPatient reports pain.",
        filename="note.pdf",
        ocr_backend=FakeOcrBackend(fixed_confidence=0.4, low_confidence_threshold=0.7),
        embedding_backend=FakeEmbeddingBackend(dimension=8),
        vector_store=vector_store,
    )
    assert result["flagged_pages"] == [1]


def test_process_document_requires_vector_store():
    with pytest.raises(ValueError):
        process_document(
            document_id="doc-3",
            tenant_id="t1",
            matter_or_patient_id="matter-1",
            confidentiality_tier=ConfidentialityTier.STANDARD,
            industry=TenantIndustry.LEGAL,
            file_bytes=b"text",
            filename="x.pdf",
            ocr_backend=FakeOcrBackend(),
            embedding_backend=FakeEmbeddingBackend(),
            vector_store=None,
        )
