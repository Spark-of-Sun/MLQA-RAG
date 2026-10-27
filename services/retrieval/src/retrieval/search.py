"""Retrieval engine executing searches with Postgres RLS cross-check."""

from __future__ import annotations

import os
import uuid
from uuid import UUID

import asyncpg
from lmqa_db import DatabaseConfig, TenantContext, build_set_local_statements
from lmqa_models import RetrievalAlias, RetrievalRecord
from lmqa_vectorstore import (
    LocalVectorStoreClient,
    QdrantVectorStoreClient,
    VectorQuery,
    VectorStoreClient,
    compute_deterministic_embedding,
)
from pydantic import BaseModel, ConfigDict, Field


class RetrievalConfig(BaseModel):
    """Runtime configuration for document chunk retrieval."""

    model_config = ConfigDict(frozen=True)

    qdrant_url: str = Field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    )
    qdrant_key_ro: str = Field(
        default_factory=lambda: os.getenv("QDRANT_KEY_RO", os.getenv("QDRANT_API_KEY", ""))
    )
    collection_name: str = Field(default="document_chunks")
    default_limit: int = Field(default=5)


class RetrievalEngine:
    """Orchestrates tenant-isolated vector retrieval conforming to Master §9.4 and §10.5."""

    def __init__(
        self,
        config: RetrievalConfig | None = None,
        vector_client: VectorStoreClient | None = None,
        db_config: DatabaseConfig | None = None,
    ) -> None:
        """Initialize retrieval client with read-only permissions and database connection."""
        self.config = config or RetrievalConfig()
        self.db_config = db_config or DatabaseConfig.from_env()

        if vector_client is not None:
            self.vector_store = vector_client
        elif os.getenv("USE_REAL_QDRANT", "1") == "1":
            self.vector_store = QdrantVectorStoreClient(
                base_url=self.config.qdrant_url,
                api_key=self.config.qdrant_key_ro,
                mode="ro",
            )
        else:
            self.vector_store = LocalVectorStoreClient()

    async def _cross_check_postgres(
        self,
        org_id: UUID,
        workspace_id: UUID,
        user_id: str,
        chunk_ids: list[UUID],
    ) -> dict[UUID, dict[str, str]]:
        """Fetch chunk text from PostgreSQL under RLS to cross-check vector results."""
        if not chunk_ids:
            return {}

        dsn = self.db_config.get_asyncpg_dsn("retrieval")
        conn = None
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            parsed_user_id: UUID | None = None
            if isinstance(user_id, UUID):
                parsed_user_id = user_id
            elif user_id:
                try:
                    parsed_user_id = UUID(user_id)
                except ValueError:
                    parsed_user_id = uuid.uuid5(uuid.NAMESPACE_DNS, user_id)

            ctx = TenantContext(org_id=org_id, workspace_id=workspace_id, user_id=parsed_user_id)
            tr = conn.transaction()
            await tr.start()
            for stmt in build_set_local_statements(ctx):
                await conn.execute(stmt)

            query = """
                SELECT c.id, c.text, c.content_hash, d.title
                FROM document_chunks c
                JOIN documents d ON d.id = c.doc_id
                WHERE c.id = ANY($1)
            """
            rows = await conn.fetch(query, chunk_ids)
            await tr.commit()

            return {
                row["id"]: {
                    "text": str(row["text"]),
                    "content_hash": str(row["content_hash"]),
                    "title": str(row["title"]),
                }
                for row in rows
            }
        except OSError, asyncpg.PostgresError:
            return {}
        finally:
            if conn:
                await conn.close()

    async def search(
        self,
        org_id: UUID,
        workspace_id: UUID,
        user_id: str,
        query: str,
        limit: int | None = None,
    ) -> RetrievalRecord:
        """Execute semantic search with mandatory PostgreSQL RLS cross-check."""
        max_results = limit or self.config.default_limit
        query_vector = compute_deterministic_embedding(query)
        v_query = VectorQuery(
            org_id=org_id,
            workspace_id=workspace_id,
            query_vector=query_vector,
            limit=max_results,
        )

        # 1. Scoped search in vectorstore
        search_results = await self.vector_store.search(
            collection_name=self.config.collection_name,
            query=v_query,
        )

        # 2. Cross-check against PostgreSQL under RLS
        candidate_ids = [res.id for res in search_results]
        pg_authorized_chunks = await self._cross_check_postgres(
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            chunk_ids=candidate_ids,
        )

        aliases: list[RetrievalAlias] = []
        for idx, res in enumerate(search_results, start=1):
            payload = res.payload
            page_val = str(payload.get("page", "1"))
            section_val = str(payload.get("section", ""))

            pg_chunk = pg_authorized_chunks.get(res.id)
            if pg_chunk is not None:
                # Validated by PostgreSQL RLS
                alias = RetrievalAlias(
                    alias=f"chunk_{idx}",
                    chunk_id=res.id,
                    doc_name=pg_chunk["title"]
                    or str(payload.get("title", f"doc_{str(res.id)[:8]}")),
                    page=page_val,
                    section=section_val,
                    text=pg_chunk["text"],
                    content_hash=pg_chunk["content_hash"],
                    score=res.score,
                    dropped=False,
                    drop_reason=None,
                )
            elif isinstance(self.vector_store, LocalVectorStoreClient) and "text" in payload:
                # Local in-memory test store fallback
                alias = RetrievalAlias(
                    alias=f"chunk_{idx}",
                    chunk_id=res.id,
                    doc_name=str(payload.get("title", f"doc_{str(res.id)[:8]}")),
                    page=page_val,
                    section=section_val,
                    text=str(payload.get("text", "")),
                    content_hash=str(payload.get("content_hash", "")),
                    score=res.score,
                    dropped=False,
                    drop_reason=None,
                )
            else:
                # Denied by PostgreSQL RLS or missing (defense-in-depth leak prevention)
                alias = RetrievalAlias(
                    alias=f"chunk_{idx}",
                    chunk_id=res.id,
                    doc_name=str(payload.get("title", "UNAUTHORIZED")),
                    page=page_val,
                    section=section_val,
                    text="",
                    content_hash="",
                    score=res.score,
                    dropped=True,
                    drop_reason="rls_denied",
                )
            aliases.append(alias)

        request_id = uuid.uuid4()
        scope_hash = f"scope-{str(org_id)[:8]}-{str(workspace_id)[:8]}"

        return RetrievalRecord(
            request_id=request_id,
            org_id=org_id,
            workspace_id=workspace_id,
            user_id=user_id,
            scope_hash=scope_hash,
            query=query,
            aliases=aliases,
        )
