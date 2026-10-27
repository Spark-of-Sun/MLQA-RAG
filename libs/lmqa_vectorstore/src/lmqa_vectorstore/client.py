"""Vector store client interface and contract enforcement."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from lmqa_vectorstore.models import VectorPoint, VectorQuery, VectorSearchResult


class VectorStoreClient(Protocol):
    """Protocol for vector store operations enforcing tenant isolation."""

    async def ensure_collection(self, collection_name: str, vector_size: int = 384) -> None:
        """Create collection if it does not exist."""
        ...

    async def upsert(
        self,
        collection_name: str,
        points: list[VectorPoint],
        org_id: UUID,
        workspace_id: UUID,
    ) -> None:
        """Upsert vector points verifying tenant isolation fields in each point payload."""
        ...

    async def search(
        self,
        collection_name: str,
        query: VectorQuery,
    ) -> list[VectorSearchResult]:
        """Search vector collection enforcing strict org_id and workspace_id filters."""
        ...

    async def delete_document(
        self,
        collection_name: str,
        org_id: UUID,
        workspace_id: UUID,
        doc_id: UUID,
    ) -> None:
        """Delete all vectors associated with a document within a workspace."""
        ...
