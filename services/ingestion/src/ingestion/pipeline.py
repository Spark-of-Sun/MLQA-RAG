"""Document ingestion pipeline orchestrating scan, parse, chunk, store, and index."""

from __future__ import annotations

import hashlib
import os
import uuid
from typing import TYPE_CHECKING

import asyncpg
from lmqa_db import DatabaseConfig, TenantContext, build_set_local_statements
from lmqa_objectstore import ObjectStoreClient, get_storage_client
from lmqa_vectorstore import (
    LocalVectorStoreClient,
    QdrantVectorStoreClient,
    VectorPoint,
    VectorStoreClient,
    compute_deterministic_embedding,
)

from ingestion.chunker import StructuralChunker
from ingestion.config import IngestionConfig
from ingestion.parser import DocumentParser
from ingestion.scanner import DocumentScanner

if TYPE_CHECKING:
    from uuid import UUID

    from lmqa_models import Chunk

    from ingestion.models import IngestionRequest


class IngestionPipeline:
    """End-to-end document processing pipeline."""

    def __init__(
        self,
        config: IngestionConfig | None = None,
        storage_client: ObjectStoreClient | None = None,
        vector_client: VectorStoreClient | None = None,
    ) -> None:
        """Initialize pipeline with configured dependencies."""
        self.config = config or IngestionConfig()
        self.scanner = DocumentScanner(max_size_bytes=self.config.max_file_size_bytes)
        self.parser = DocumentParser(ocr_enabled=self.config.ocr_enabled)
        self.chunker = StructuralChunker(
            min_tokens=self.config.min_chunk_tokens,
            target_min=self.config.target_chunk_tokens_min,
            target_max=self.config.target_chunk_tokens_max,
            max_tokens=self.config.max_chunk_tokens,
        )
        self.storage = storage_client or get_storage_client()
        if vector_client is not None:
            self.vector_store = vector_client
        elif os.getenv("USE_REAL_QDRANT", "1") == "1":
            self.vector_store = QdrantVectorStoreClient(
                base_url=self.config.qdrant_url,
                api_key=self.config.qdrant_api_key,
                mode="rw",
            )
        else:
            self.vector_store = LocalVectorStoreClient()

        self.db_config = DatabaseConfig.from_env()

    async def init_upload(
        self,
        org_id: UUID,
        workspace_id: UUID,
        title: str,
        content_type: str,
        size_bytes: int,
    ) -> UUID:
        """Initialize upload record in the database."""
        _ = content_type
        _ = size_bytes
        doc_id = uuid.uuid4()
        dsn = self.db_config.get_asyncpg_dsn("ingestion")

        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            ctx = TenantContext(org_id=org_id, workspace_id=workspace_id)
            tr = conn.transaction()
            await tr.start()
            for stmt in build_set_local_statements(ctx):
                await conn.execute(stmt)

            await conn.execute(
                """
                INSERT INTO documents (id, org_id, workspace_id, title, status)
                VALUES ($1, $2, $3, $4, 'uploading')
                """,
                doc_id,
                org_id,
                workspace_id,
                title,
            )
            await tr.commit()
        finally:
            await conn.close()

        return doc_id

    async def process_document(self, request: IngestionRequest) -> list[Chunk]:
        """Execute full ingestion: scan -> parse -> chunk -> store -> index."""
        target = request.target
        # 1. Checksum validation
        actual_sha256 = hashlib.sha256(request.raw_data).hexdigest()
        if request.expected_sha256 and actual_sha256.lower() != request.expected_sha256.lower():
            msg = f"Checksum mismatch: expected {request.expected_sha256}, got {actual_sha256}"
            raise ValueError(msg)

        # 2. Scanner (Malware, magic bytes, active content)
        self.scanner.scan(request.raw_data, request.declared_content_type)

        # 3. Parser (Text extraction, page numbering)
        pages = self.parser.parse(request.raw_data, request.declared_content_type)
        page_tuples = [(p.page_num, p.text) for p in pages]

        # 4. Chunker (Structural chunking with mandatory preamble)
        chunks = self.chunker.chunk_document(target, page_tuples)

        # 5. Object Storage persistence
        self.storage.put_document(
            tenant_id=str(target.org_id),
            document_id=str(target.doc_id),
            data=request.raw_data,
            content_type=request.declared_content_type,
        )

        # 6. Database persistence under RLS
        dsn = self.db_config.get_asyncpg_dsn("ingestion")
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            ctx = TenantContext(org_id=target.org_id, workspace_id=target.workspace_id)
            tr = conn.transaction()
            await tr.start()
            for stmt in build_set_local_statements(ctx):
                await conn.execute(stmt)

            # Insert/Update document status
            await conn.execute(
                """
                INSERT INTO documents (id, org_id, workspace_id, title, status)
                VALUES ($1, $2, $3, $4, 'chunking')
                ON CONFLICT (id) DO UPDATE SET status = 'chunking', title = EXCLUDED.title
                """,
                target.doc_id,
                target.org_id,
                target.workspace_id,
                target.title,
            )

            # Clear any existing chunks for this document for idempotent re-processing
            await conn.execute("DELETE FROM document_chunks WHERE doc_id = $1", target.doc_id)

            # Insert chunks
            for ch in chunks:
                await conn.execute(
                    """
                    INSERT INTO document_chunks (
                        id, org_id, workspace_id, doc_id, ordinal, text, content_hash
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    ch.chunk_id,
                    ch.org_id,
                    ch.workspace_id,
                    ch.metadata.doc_id,
                    ch.metadata.ordinal,
                    ch.text,
                    ch.content_hash,
                )

            # Mark document available
            await conn.execute(
                "UPDATE documents SET status = 'available' WHERE id = $1",
                target.doc_id,
            )
            await tr.commit()
        finally:
            await conn.close()

        # 7. Vector indexation
        await self.vector_store.ensure_collection(self.config.qdrant_collection, vector_size=384)
        await self.vector_store.delete_document(
            self.config.qdrant_collection,
            org_id=target.org_id,
            workspace_id=target.workspace_id,
            doc_id=target.doc_id,
        )

        vector_points: list[VectorPoint] = []
        for ch in chunks:
            embedding = compute_deterministic_embedding(ch.text, dim=384)
            pt = VectorPoint(
                id=ch.chunk_id,
                vector=embedding,
                payload={
                    "org_id": str(ch.org_id),
                    "workspace_id": str(ch.workspace_id),
                    "doc_id": str(ch.metadata.doc_id),
                    "chunk_id": str(ch.chunk_id),
                    "ordinal": ch.metadata.ordinal,
                    "kind": ch.metadata.kind,
                    "title": ch.metadata.title,
                    "page": ch.metadata.page,
                    "section": ch.metadata.section,
                    "content_hash": ch.content_hash,
                    "text": ch.text,
                },
            )
            vector_points.append(pt)

        await self.vector_store.upsert(
            self.config.qdrant_collection,
            vector_points,
            org_id=target.org_id,
            workspace_id=target.workspace_id,
        )

        return chunks

    async def delete_document(
        self,
        org_id: UUID,
        workspace_id: UUID,
        doc_id: UUID,
    ) -> None:
        """Cryptographically erase document and remove vectors."""
        # 1. Delete vectors
        await self.vector_store.delete_document(
            self.config.qdrant_collection,
            org_id=org_id,
            workspace_id=workspace_id,
            doc_id=doc_id,
        )

        # 2. Erase from storage and write tombstone
        self.storage.delete_document(tenant_id=str(org_id), document_id=str(doc_id))

        # 3. Delete database records under RLS
        dsn = self.db_config.get_asyncpg_dsn("ingestion")
        conn = await asyncpg.connect(dsn, timeout=5)
        try:
            ctx = TenantContext(org_id=org_id, workspace_id=workspace_id)
            tr = conn.transaction()
            await tr.start()
            for stmt in build_set_local_statements(ctx):
                await conn.execute(stmt)

            await conn.execute("DELETE FROM document_chunks WHERE doc_id = $1", doc_id)
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)
            await tr.commit()
        finally:
            await conn.close()
