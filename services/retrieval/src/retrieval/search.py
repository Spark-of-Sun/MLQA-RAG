"""Retrieval engine executing tenant-isolated semantic and vector searches."""

from __future__ import annotations

import os
import uuid
from uuid import UUID

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
    """Orchestrates tenant-isolated vector retrieval conforming to Master §9.4."""

    def __init__(
        self,
        config: RetrievalConfig | None = None,
        vector_client: VectorStoreClient | None = None,
    ) -> None:
        """Initialize retrieval client with read-only permissions."""
        self.config = config or RetrievalConfig()
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

    async def search(
        self,
        org_id: UUID,
        workspace_id: UUID,
        user_id: str,
        query: str,
        limit: int | None = None,
    ) -> RetrievalRecord:
        """Execute semantic search and build immutable retrieval record ledger."""
        max_results = limit or self.config.default_limit
        query_vector = compute_deterministic_embedding(query)
        v_query = VectorQuery(
            org_id=org_id,
            workspace_id=workspace_id,
            query_vector=query_vector,
            limit=max_results,
        )

        search_results = await self.vector_store.search(
            collection_name=self.config.collection_name,
            query=v_query,
        )

        aliases: list[RetrievalAlias] = []
        for idx, res in enumerate(search_results, start=1):
            payload = res.payload
            chunk_text = str(payload.get("text", ""))
            content_hash = str(payload.get("content_hash", ""))
            doc_name = str(payload.get("title", f"doc_{str(res.id)[:8]}"))
            page_val = str(payload.get("page", "1"))
            section_val = str(payload.get("section", ""))

            alias = RetrievalAlias(
                alias=f"chunk_{idx}",
                chunk_id=res.id,
                doc_name=doc_name,
                page=page_val,
                section=section_val,
                text=chunk_text,
                content_hash=content_hash,
                score=res.score,
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
