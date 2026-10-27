"""Integration tests for legal corpus ingestion and RLS isolation.

Master System Design §11.1 & SCOPE_CUTS_M1a.md (Profile mvp-a).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import asyncpg
import pytest
from lmqa_db import DatabaseConfig, TenantContext, build_set_local_statements

from tools.load_corpus.main import (
    DEFAULT_TENANT_ALPHA_ORG,
    DEFAULT_TENANT_ALPHA_WS,
    DEFAULT_TENANT_BETA_ORG,
    DEFAULT_TENANT_BETA_WS,
    load_corpus,
)


@pytest.mark.stage4
@pytest.mark.integration
@pytest.mark.asyncio
async def test_legal_corpus_ingestion_and_isolation() -> None:
    """Verify all 25 legal documents ingest cleanly under tenant RLS and Qdrant."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    manifest_path = repo_root / "corpus" / "manifest.toml"
    data_dir = repo_root / "corpus" / "data" / "legal"
    test_collection = f"test_corpus_{uuid.uuid4().hex[:8]}"

    # Ingest legal corpus for Tenant Alpha
    doc_count, chunk_count = await load_corpus(
        manifest_path=manifest_path,
        data_dir=data_dir,
        org_id=DEFAULT_TENANT_ALPHA_ORG,
        workspace_id=DEFAULT_TENANT_ALPHA_WS,
        collection_name=test_collection,
    )

    assert doc_count == 25
    assert chunk_count >= 300

    cfg = DatabaseConfig.from_env()
    conn = await asyncpg.connect(cfg.get_asyncpg_dsn("retrieval"), timeout=5)
    try:
        # 1. Fail-closed: No context returns 0 rows
        count_no_ctx = await conn.fetchval("SELECT count(*) FROM documents")
        assert count_no_ctx == 0

        # 2. Tenant Alpha reads its own 25 documents and chunks
        ctx_alpha = TenantContext(
            org_id=DEFAULT_TENANT_ALPHA_ORG, workspace_id=DEFAULT_TENANT_ALPHA_WS
        )
        tr = conn.transaction()
        await tr.start()
        for stmt in build_set_local_statements(ctx_alpha):
            await conn.execute(stmt)

        alpha_docs = await conn.fetchval("SELECT count(*) FROM documents")
        alpha_chunks = await conn.fetchval("SELECT count(*) FROM document_chunks")
        assert alpha_docs == 25
        assert alpha_chunks == chunk_count
        await tr.commit()

        # 3. Tenant Beta sees 0 documents and 0 chunks (Strict RLS Isolation)
        ctx_beta = TenantContext(
            org_id=DEFAULT_TENANT_BETA_ORG, workspace_id=DEFAULT_TENANT_BETA_WS
        )
        tr_beta = conn.transaction()
        await tr_beta.start()
        for stmt in build_set_local_statements(ctx_beta):
            await conn.execute(stmt)

        beta_docs = await conn.fetchval("SELECT count(*) FROM documents")
        beta_chunks = await conn.fetchval("SELECT count(*) FROM document_chunks")
        assert beta_docs == 0
        assert beta_chunks == 0
        await tr_beta.commit()
    finally:
        await conn.close()


@pytest.mark.stage4
@pytest.mark.integration
@pytest.mark.asyncio
async def test_legal_corpus_idempotent_reloading() -> None:
    """Verify that re-running corpus loading is idempotent and does not duplicate chunks."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    manifest_path = repo_root / "corpus" / "manifest.toml"
    data_dir = repo_root / "corpus" / "data" / "legal"
    test_collection = f"test_idempotent_{uuid.uuid4().hex[:8]}"

    # Run 1
    docs_1, chunks_1 = await load_corpus(
        manifest_path=manifest_path,
        data_dir=data_dir,
        org_id=DEFAULT_TENANT_ALPHA_ORG,
        workspace_id=DEFAULT_TENANT_ALPHA_WS,
        collection_name=test_collection,
    )

    # Run 2 (re-load)
    docs_2, chunks_2 = await load_corpus(
        manifest_path=manifest_path,
        data_dir=data_dir,
        org_id=DEFAULT_TENANT_ALPHA_ORG,
        workspace_id=DEFAULT_TENANT_ALPHA_WS,
        collection_name=test_collection,
    )

    assert docs_1 == docs_2 == 25
    assert chunks_1 == chunks_2
