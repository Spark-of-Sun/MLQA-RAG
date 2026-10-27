"""Comprehensive tests for document ingestion, parsing, chunking, and pipeline."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
import zlib

import asyncpg
import httpx
import pytest
from ingestion.api import app
from ingestion.chunker import StructuralChunker
from ingestion.config import IngestionConfig
from ingestion.models import DocumentTarget, IngestionRequest
from ingestion.parser import DocumentParser, OcrDisabledError
from ingestion.pipeline import IngestionPipeline
from ingestion.scanner import EICAR_SIGNATURE, DocumentScanner, ScanValidationError
from lmqa_db import DatabaseConfig, TenantContext, build_set_local_statements
from lmqa_objectstore import LocalObjectStoreClient
from lmqa_vectorstore import QdrantVectorStoreClient, VectorQuery, compute_deterministic_embedding


def _create_minimal_pdf(text: str) -> bytes:
    """Helper creating a minimal valid PDF with a FlateDecode text stream."""
    stream_content = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode("latin1")
    compressed = zlib.compress(stream_content)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Contents 4 0 R>> endobj\n"
        b"4 0 obj <</Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode>>\n"
        b"stream\n" + compressed + b"\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n"
        b"trailer <</Size 5 /Root 1 0 R>>\nstartxref\n500\n%%EOF"
    )


@pytest.mark.stage0
@pytest.mark.unit
def test_scanner_eicar_rejection() -> None:
    """Verify scanner rejects EICAR malware signature."""
    scanner = DocumentScanner()
    with pytest.raises(ScanValidationError, match="Antivirus alert: EICAR test signature"):
        scanner.scan(EICAR_SIGNATURE, "text/plain")


@pytest.mark.stage0
@pytest.mark.unit
def test_scanner_pdf_magic_and_active_content() -> None:
    """Verify scanner detects missing magic bytes and PDF active content."""
    scanner = DocumentScanner()
    # Missing magic
    with pytest.raises(ScanValidationError, match="PDF magic byte header missing"):
        scanner.scan(b"NOT_A_PDF", "application/pdf")

    # Active content (/JavaScript)
    malicious_pdf = b"%PDF-1.4\n/JavaScript (app.alert('pwned'));\n%%EOF"
    with pytest.raises(ScanValidationError, match="PDF active content detected"):
        scanner.scan(malicious_pdf, "application/pdf")


@pytest.mark.stage0
@pytest.mark.unit
def test_parser_pdf_text_extraction() -> None:
    """Verify parser extracts text layer from FlateDecode streams."""
    parser = DocumentParser(ocr_enabled=False)
    pdf_bytes = _create_minimal_pdf("Confidential Master Services Agreement")
    pages = parser.parse(pdf_bytes, "application/pdf")
    assert len(pages) == 1
    assert "Confidential Master Services Agreement" in pages[0].text


@pytest.mark.stage0
@pytest.mark.unit
def test_parser_ocr_disabled_failsafe() -> None:
    """Verify empty pages raise OcrDisabledError when OCR is disabled (DR-15)."""
    parser = DocumentParser(ocr_enabled=False)
    # PDF with no text stream content
    empty_pdf = (
        b"%PDF-1.4\n1 0 obj <</Type /Catalog>> endobj\nxref\n0 2\ntrailer <</Root 1 0 R>>\n%%EOF"
    )
    with pytest.raises(OcrDisabledError, match="OCR is disabled"):
        parser.parse(empty_pdf, "application/pdf")


@pytest.mark.stage0
@pytest.mark.unit
def test_chunker_preamble_and_sections() -> None:
    """Verify chunker detects preamble text and partitions numbered articles."""
    chunker = StructuralChunker(min_tokens=10, max_tokens=1200)
    target = DocumentTarget(
        doc_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        title="Merger Agreement",
    )
    contract_text = (
        "This Agreement is entered into on October 27, 2026 by Acme Corp and Beta LLC.\n\n"
        "ARTICLE 1. DEFINITIONS\n"
        "Affiliate means any entity controlling or controlled by a party.\n\n"
        "ARTICLE 2. COVENANTS AND PAYMENT\n"
        "Beta LLC shall remit consideration within 30 days of closing."
    )

    chunks = chunker.chunk_document(target, [(1, contract_text)])
    assert len(chunks) == 3

    # First chunk must be preamble
    assert chunks[0].metadata.kind == "preamble"
    assert "Acme Corp and Beta LLC" in chunks[0].text

    # Second chunk is Article 1
    assert chunks[1].metadata.kind == "section"
    assert "ARTICLE 1" in chunks[1].text

    # Third chunk is Article 2
    assert chunks[2].metadata.kind == "section"
    assert "ARTICLE 2" in chunks[2].text


@pytest.mark.stage0
@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_ingestion_pipeline_end_to_end() -> None:
    """End-to-end integration test: store in DB and Qdrant, verify RLS and erasure."""
    org_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    db_config = DatabaseConfig.from_env()
    admin_conn = await asyncpg.connect(
        "postgresql://lmqa_admin:lmqa_secret@localhost:5432/lmqa", timeout=5
    )
    try:
        # Create org and workspace
        await admin_conn.execute("INSERT INTO orgs (id, name) VALUES ($1, $2)", org_id, "Test Org")
        await admin_conn.execute(
            "INSERT INTO workspaces (id, org_id, name) VALUES ($1, $2, $3)",
            workspace_id,
            org_id,
            "Legal Workspace",
        )
    finally:
        await admin_conn.close()

    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = LocalObjectStoreClient(base_dir=tmp_dir)
        qdrant = QdrantVectorStoreClient(base_url="http://127.0.0.1:6333")
        collection = f"chunks_{uuid.uuid4().hex[:8]}"
        config = IngestionConfig(qdrant_collection=collection)

        pipeline = IngestionPipeline(config=config, storage_client=storage, vector_client=qdrant)

        contract_content = (
            b"MUTUAL NONDISCLOSURE AGREEMENT\n"
            b"Effective as of November 1, 2026 by Alpha Corp and Gamma Inc.\n\n"
            b"ARTICLE 1. CONFIDENTIAL INFORMATION\n"
            b"All proprietary code, trade secrets, and financial models are confidential.\n\n"
            b"ARTICLE 2. TERM AND TERMINATION\n"
            b"This Agreement remains in effect for three (3) years."
        )

        target = DocumentTarget(
            doc_id=doc_id,
            org_id=org_id,
            workspace_id=workspace_id,
            title="NDA_Alpha_Gamma.txt",
        )
        req = IngestionRequest(
            target=target,
            raw_data=contract_content,
            declared_content_type="text/plain",
            expected_sha256=hashlib.sha256(contract_content).hexdigest(),
        )

        # 1. Execute ingestion pipeline
        chunks = await pipeline.process_document(req)
        assert len(chunks) >= 2
        assert chunks[0].metadata.kind == "preamble"

        # 2. Verify database records under service role lmqa_ingestion with RLS
        ingestion_dsn = db_config.get_asyncpg_dsn("ingestion")
        service_conn = await asyncpg.connect(ingestion_dsn, timeout=5)
        try:
            ctx = TenantContext(org_id=org_id, workspace_id=workspace_id)
            tr = service_conn.transaction()
            await tr.start()
            for stmt in build_set_local_statements(ctx):
                await service_conn.execute(stmt)

            doc_row = await service_conn.fetchrow(
                "SELECT status FROM documents WHERE id = $1", doc_id
            )
            assert doc_row is not None
            assert doc_row["status"] == "available"

            chunk_rows = await service_conn.fetch(
                "SELECT id, text FROM document_chunks WHERE doc_id = $1 ORDER BY ordinal ASC",
                doc_id,
            )
            assert len(chunk_rows) == len(chunks)
            await tr.rollback()
        finally:
            await service_conn.close()

        # 3. Verify Qdrant search works
        q = VectorQuery(
            query_vector=compute_deterministic_embedding("trade secrets proprietary code"),
            org_id=org_id,
            workspace_id=workspace_id,
        )
        found_vectors = await qdrant.search(collection, q)
        assert len(found_vectors) >= 1

        # Mismatched org must find 0 vectors
        q_foreign = VectorQuery(
            query_vector=compute_deterministic_embedding("trade secrets proprietary code"),
            org_id=uuid.uuid4(),
            workspace_id=workspace_id,
        )
        assert len(await qdrant.search(collection, q_foreign)) == 0

        # 4. Cryptographic erasure / deletion
        await pipeline.delete_document(org_id, workspace_id, doc_id)

        # Verify vectors deleted
        assert len(await qdrant.search(collection, q)) == 0


@pytest.mark.stage0
@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingestion_api_endpoints() -> None:
    """Test FastAPI upload endpoints."""
    org_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    # Pre-provision org and workspace so foreign keys succeed
    admin_conn = await asyncpg.connect(
        "postgresql://lmqa_admin:lmqa_secret@localhost:5432/lmqa", timeout=5
    )
    try:
        await admin_conn.execute(
            "INSERT INTO orgs (id, name) VALUES ($1, $2)", org_id, "API Test Org"
        )
        await admin_conn.execute(
            "INSERT INTO workspaces (id, org_id, name) VALUES ($1, $2, $3)",
            workspace_id,
            org_id,
            "API Test Workspace",
        )
    finally:
        await admin_conn.close()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Health probes
        live_resp = await client.get("/health/live")
        assert live_resp.status_code == 200
        assert live_resp.json() == {"status": "ok"}

        # 2. Upload init endpoint
        init_payload = {
            "title": "Commercial_Lease.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1024,
        }
        headers = {"X-Org-Id": str(org_id), "X-Workspace-Id": str(workspace_id)}
        resp = await client.post("/v1/documents/uploads", json=init_payload, headers=headers)
        assert resp.status_code == 201
        data = resp.json()
        assert "document_id" in data
        assert data["status"] == "uploading"

    # Clean up test rows
    admin_conn = await asyncpg.connect(
        "postgresql://lmqa_admin:lmqa_secret@localhost:5432/lmqa", timeout=5
    )
    try:
        await admin_conn.execute("DELETE FROM workspaces WHERE id = $1", workspace_id)
        await admin_conn.execute("DELETE FROM orgs WHERE id = $1", org_id)
    finally:
        await admin_conn.close()
