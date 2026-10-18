from __future__ import annotations

from uuid import uuid4

from common.logging import get_logger
from common.models import Chunk, ConfidentialityTier, TenantIndustry

from app.chunking import get_chunker
from app.embedding import EmbeddingBackend, get_embedding_backend
from app.ocr import OcrBackend, get_ocr_backend
from app.workers.vector_store import VectorStore

log = get_logger(__name__)


def process_document(
    *,
    document_id: str,
    tenant_id: str,
    matter_or_patient_id: str,
    confidentiality_tier: ConfidentialityTier,
    industry: TenantIndustry,
    file_bytes: bytes,
    filename: str,
    effective_date=None,
    ocr_backend: OcrBackend | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    vector_store: VectorStore | None = None,
) -> dict:
    """The actual ingestion pipeline: OCR -> structure-aware chunk ->
    embed -> write to vector store. A plain function with no framework/
    queue dependency, so unit tests can call it directly with fakes, and
    the Arq task below can call it with real backends built from env.
    """
    ocr_backend = ocr_backend or get_ocr_backend()
    embedding_backend = embedding_backend or get_embedding_backend()
    if vector_store is None:
        raise ValueError("vector_store must be provided — no default, to avoid silently writing to the wrong store")

    pages = ocr_backend.extract_pages(file_bytes, filename)
    flagged_pages = [p.page_number for p in pages if p.flagged_for_review]
    if flagged_pages:
        log.warning("low_confidence_pages_flagged", document_id=document_id, pages=flagged_pages)

    chunker = get_chunker(industry)
    candidates = chunker.chunk([(p.page_number, p.text) for p in pages])

    chunks = [
        Chunk(
            chunk_id=str(uuid4()),
            document_id=document_id,
            tenant_id=tenant_id,
            matter_or_patient_id=matter_or_patient_id,
            text=candidate.text,
            page=candidate.page,
            section=candidate.section,
            confidentiality_tier=confidentiality_tier,
            effective_date=effective_date,
        )
        for candidate in candidates
    ]

    if chunks:
        vectors = embedding_backend.embed([c.text for c in chunks])
        vector_store.upsert_chunks(chunks, vectors)

    log.info(
        "document_ingested",
        document_id=document_id,
        chunk_count=len(chunks),
        flagged_page_count=len(flagged_pages),
    )
    return {"document_id": document_id, "chunk_count": len(chunks), "flagged_pages": flagged_pages}


async def ingest_document(
    ctx,
    *,
    document_id: str,
    tenant_id: str,
    matter_or_patient_id: str,
    confidentiality_tier: str,
    industry: str,
    object_store_key: str,
    filename: str,
) -> dict:
    """Arq task entrypoint — the function name registered in
    WorkerSettings.functions. Fetches the original file from object
    storage, runs process_document with real backends. TODO once
    db/migrations exists: update the document's status to 'indexed' or
    'failed' in Postgres instead of only logging the outcome.
    """
    from app.state import build_object_store_client
    from app.workers.vector_store import QdrantVectorStore

    object_store = build_object_store_client()
    file_bytes = object_store.get_object(object_store_key)

    vector_store = QdrantVectorStore()
    result = process_document(
        document_id=document_id,
        tenant_id=tenant_id,
        matter_or_patient_id=matter_or_patient_id,
        confidentiality_tier=ConfidentialityTier(confidentiality_tier),
        industry=TenantIndustry(industry),
        file_bytes=file_bytes,
        filename=filename,
        vector_store=vector_store,
    )
    return result
