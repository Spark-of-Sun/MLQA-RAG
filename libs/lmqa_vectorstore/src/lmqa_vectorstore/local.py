"""Local in-memory vector store client with strict isolation guarantees."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lmqa_vectorstore.embeddings import cosine_similarity
from lmqa_vectorstore.models import VectorSearchResult

if TYPE_CHECKING:
    from uuid import UUID

    from lmqa_vectorstore.models import VectorPoint, VectorQuery


class LocalVectorStoreClient:
    """In-memory vector store client with exact tenant and workspace isolation."""

    def __init__(self) -> None:
        """Initialize empty collections map."""
        # collection_name -> list of VectorPoint
        self._collections: dict[str, list[VectorPoint]] = {}

    async def ensure_collection(self, collection_name: str, vector_size: int = 384) -> None:
        """Create collection if it does not exist."""
        _ = vector_size
        if collection_name not in self._collections:
            self._collections[collection_name] = []

    async def upsert(
        self,
        collection_name: str,
        points: list[VectorPoint],
        org_id: UUID,
        workspace_id: UUID,
    ) -> None:
        """Upsert points validating that payloads belong to the specified org and workspace."""
        if collection_name not in self._collections:
            await self.ensure_collection(collection_name)

        org_str = str(org_id)
        ws_str = str(workspace_id)

        for pt in points:
            pt_org = str(pt.payload.get("org_id"))
            pt_ws = str(pt.payload.get("workspace_id"))
            if pt_org != org_str or pt_ws != ws_str:
                msg = (
                    f"Vector point payload isolation mismatch: "
                    f"{pt_org}/{pt_ws} != {org_str}/{ws_str}"
                )
                raise ValueError(msg)

        # Replace existing points with same ID or append
        existing = {p.id: p for p in self._collections[collection_name]}
        for pt in points:
            existing[pt.id] = pt
        self._collections[collection_name] = list(existing.values())

    async def search(
        self,
        collection_name: str,
        query: VectorQuery,
    ) -> list[VectorSearchResult]:
        """Search collection strictly restricted to matching org_id and workspace_id."""
        if collection_name not in self._collections:
            return []

        org_str = str(query.org_id)
        ws_str = str(query.workspace_id)

        candidates: list[VectorSearchResult] = []
        for pt in self._collections[collection_name]:
            # Mandatory isolation filter check
            if str(pt.payload.get("org_id")) != org_str:
                continue
            if str(pt.payload.get("workspace_id")) != ws_str:
                continue

            # Optional additional filters
            if query.filter_criteria:
                match = True
                for k, v in query.filter_criteria.items():
                    if pt.payload.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            score = cosine_similarity(query.query_vector, pt.vector)
            candidates.append(VectorSearchResult(id=pt.id, score=score, payload=pt.payload))

        # Sort descending by score
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates[: query.limit]

    async def delete_document(
        self,
        collection_name: str,
        org_id: UUID,
        workspace_id: UUID,
        doc_id: UUID,
    ) -> None:
        """Delete all vectors for the document within the org and workspace."""
        if collection_name not in self._collections:
            return

        org_str = str(org_id)
        ws_str = str(workspace_id)
        doc_str = str(doc_id)

        self._collections[collection_name] = [
            pt
            for pt in self._collections[collection_name]
            if not (
                str(pt.payload.get("org_id")) == org_str
                and str(pt.payload.get("workspace_id")) == ws_str
                and str(pt.payload.get("doc_id")) == doc_str
            )
        ]
