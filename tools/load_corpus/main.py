"""Load corpus documents from manifest into PostgreSQL and Qdrant under tenant RLS.

Master System Design §11.1 & SCOPE_CUTS_M1a.md (Profile mvp-a).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
from ingestion.config import IngestionConfig
from ingestion.models import DocumentTarget, IngestionRequest
from ingestion.pipeline import IngestionPipeline
from lmqa_db import DatabaseConfig

if TYPE_CHECKING:
    from uuid import UUID

DEFAULT_TENANT_ALPHA_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_TENANT_ALPHA_WS = uuid.UUID("00000000-0000-0000-0000-000000000011")

DEFAULT_TENANT_BETA_ORG = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEFAULT_TENANT_BETA_WS = uuid.UUID("00000000-0000-0000-0000-000000000022")


async def _connect_admin(cfg: DatabaseConfig) -> asyncpg.Connection:
    """Connect as admin user to manage organizations and workspaces."""
    password = cfg.password or "lmqa_secret"
    try:
        return await asyncpg.connect(
            host=cfg.host,
            port=5432,
            user=cfg.user,
            password=password,
            database=cfg.database,
            timeout=5,
        )
    except OSError, asyncpg.PostgresError:
        return await asyncpg.connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=password,
            database=cfg.database,
            timeout=5,
        )


async def ensure_seed_tenants(cfg: DatabaseConfig) -> None:
    """Ensure standard seed organizations and workspaces exist in PostgreSQL."""
    conn = await _connect_admin(cfg)
    try:
        tenants = [
            (
                DEFAULT_TENANT_ALPHA_ORG,
                "Alpha Legal Organization",
                DEFAULT_TENANT_ALPHA_WS,
                "Alpha Commercial Workspace",
            ),
            (
                DEFAULT_TENANT_BETA_ORG,
                "Beta Corporate Organization",
                DEFAULT_TENANT_BETA_WS,
                "Beta Corporate Workspace",
            ),
        ]
        for org_id, org_name, ws_id, ws_name in tenants:
            await conn.execute(
                """
                INSERT INTO orgs (id, name, state)
                VALUES ($1, $2, 'active')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """,
                org_id,
                org_name,
            )
            await conn.execute(
                """
                INSERT INTO workspaces (id, org_id, name, state)
                VALUES ($1, $2, $3, 'active')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """,
                ws_id,
                org_id,
                ws_name,
            )
    finally:
        await conn.close()


async def load_corpus(
    manifest_path: Path,
    data_dir: Path,
    org_id: UUID,
    workspace_id: UUID,
    collection_name: str = "document_chunks",
) -> tuple[int, int]:
    """Ingest legal documents from manifest into PostgreSQL and Qdrant.

    Returns:
        tuple[int, int]: (documents_ingested_count, total_chunks_count)
    """
    if not manifest_path.is_file():
        msg = f"Corpus manifest not found: {manifest_path}"
        raise FileNotFoundError(msg)

    raw_manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    all_docs = raw_manifest.get("documents", [])
    legal_docs = [d for d in all_docs if d.get("domain") == "legal"]

    if not legal_docs:
        msg = "No legal documents found in manifest"
        raise ValueError(msg)

    cfg = DatabaseConfig.from_env()
    await ensure_seed_tenants(cfg)

    ingest_cfg = IngestionConfig(qdrant_collection=collection_name)
    pipeline = IngestionPipeline(config=ingest_cfg)

    print(
        f"Starting ingestion of {len(legal_docs)} legal documents "
        f"for tenant {org_id}/{workspace_id}..."
    )

    total_chunks = 0
    total_preambles = 0

    for idx, doc in enumerate(legal_docs, start=1):
        doc_id_str = doc["id"]
        fmt = doc.get("format", "txt")
        file_name = f"{doc_id_str}.{fmt}"
        file_path = data_dir / file_name

        if not file_path.is_file():
            msg = f"Corpus file not found: {file_path}"
            raise FileNotFoundError(msg)

        raw_bytes = file_path.read_bytes()
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        expected_sha = doc.get("sha256")

        if expected_sha and actual_sha.lower() != expected_sha.lower():
            msg = f"Checksum mismatch for {file_name}: expected {expected_sha}, got {actual_sha}"
            raise ValueError(msg)

        doc_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, doc_id_str)
        target = DocumentTarget(
            doc_id=doc_uuid,
            org_id=org_id,
            workspace_id=workspace_id,
            title=doc.get("title", doc_id_str),
            doc_version=1,
        )

        content_type = "text/plain" if fmt == "txt" else f"application/{fmt}"
        request = IngestionRequest(
            target=target,
            raw_data=raw_bytes,
            declared_content_type=content_type,
            expected_sha256=expected_sha,
        )

        chunks = await pipeline.process_document(request)
        total_chunks += len(chunks)
        preamble_count = sum(1 for c in chunks if c.metadata.kind == "preamble")
        total_preambles += preamble_count

        has_pre = preamble_count > 0
        print(
            f"  [{idx:02d}/{len(legal_docs)}] Ingested {doc_id_str} "
            f"({len(chunks)} chunks, preamble={has_pre})"
        )

    print("\nIngestion Summary:")
    print(f"  Total Legal Documents Ingested: {len(legal_docs)}")
    print(f"  Total Structural Chunks:        {total_chunks}")
    print(f"  Total Preambles Built:          {total_preambles}")
    print(f"  Target Qdrant Collection:       {collection_name}")
    print("  Status:                         SUCCESS\n")

    return len(legal_docs), total_chunks


def main() -> None:
    """CLI entrypoint for loading corpus."""
    parser = argparse.ArgumentParser(description="Ingest legal corpus into LMQA-RAG")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("corpus/manifest.toml"),
        help="Path to manifest.toml",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("corpus/data/legal"),
        help="Path to legal documents directory",
    )
    parser.add_argument(
        "--org-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ALPHA_ORG,
        help="Target organization UUID",
    )
    parser.add_argument(
        "--workspace-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ALPHA_WS,
        help="Target workspace UUID",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="document_chunks",
        help="Target Qdrant collection name",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            load_corpus(
                manifest_path=args.manifest,
                data_dir=args.data_dir,
                org_id=args.org_id,
                workspace_id=args.workspace_id,
                collection_name=args.collection,
            )
        )
    except (OSError, ValueError, asyncpg.PostgresError) as exc:
        print(f"ERROR: Ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
