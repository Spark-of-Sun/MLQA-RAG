"""Qdrant REST client implementing tenant-isolated vector operations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx

from lmqa_vectorstore.models import VectorSearchResult

if TYPE_CHECKING:
    from lmqa_vectorstore.models import VectorPoint, VectorQuery

HTTP_OK = 200


class QdrantVectorStoreClient:
    """Client for Qdrant vector database via standard REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        mode: str = "rw",
    ) -> None:
        """Initialize client settings and headers supporting RO and RW API keys."""
        self.base_url = (base_url or os.getenv("QDRANT_URL", "http://127.0.0.1:6333")).rstrip("/")
        if api_key:
            resolved_key = api_key
        elif mode.lower() == "ro":
            resolved_key = os.getenv("QDRANT_KEY_RO") or os.getenv("QDRANT_API_KEY", "")
        else:
            resolved_key = os.getenv("QDRANT_KEY_RW") or os.getenv("QDRANT_API_KEY", "")

        # Ignore example placeholder command string if copied verbatim from .env.example
        if resolved_key.startswith("python3 -c"):
            resolved_key = ""

        self.api_key = resolved_key.strip()
        self.headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["api-key"] = self.api_key

    async def ensure_collection(self, collection_name: str, vector_size: int = 384) -> None:
        """Create Qdrant collection if not already present."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/collections/{collection_name}",
                headers=self.headers,
            )
            if resp.status_code == HTTP_OK:
                return

            body = {
                "vectors": {
                    "size": vector_size,
                    "distance": "Cosine",
                }
            }
            create_resp = await client.put(
                f"{self.base_url}/collections/{collection_name}",
                headers=self.headers,
                json=body,
            )
            create_resp.raise_for_status()

    async def upsert(
        self,
        collection_name: str,
        points: list[VectorPoint],
        org_id: UUID,
        workspace_id: UUID,
    ) -> None:
        """Upsert points validating tenant isolation payload values."""
        if not points:
            return

        org_str = str(org_id)
        ws_str = str(workspace_id)

        qdrant_points: list[dict[str, Any]] = []
        for pt in points:
            payload = dict(pt.payload)
            pt_org = str(payload.get("org_id"))
            pt_ws = str(payload.get("workspace_id"))
            if pt_org != org_str or pt_ws != ws_str:
                msg = f"Vector payload isolation mismatch: {pt_org}/{pt_ws} != {org_str}/{ws_str}"
                raise ValueError(msg)

            qdrant_points.append(
                {
                    "id": str(pt.id),
                    "vector": pt.vector,
                    "payload": payload,
                }
            )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.put(
                f"{self.base_url}/collections/{collection_name}/points?wait=true",
                headers=self.headers,
                json={"points": qdrant_points},
            )
            resp.raise_for_status()

    async def search(
        self,
        collection_name: str,
        query: VectorQuery,
    ) -> list[VectorSearchResult]:
        """Search points with mandatory org_id and workspace_id must-match filters."""
        must_clauses: list[dict[str, Any]] = [
            {"key": "org_id", "match": {"value": str(query.org_id)}},
            {"key": "workspace_id", "match": {"value": str(query.workspace_id)}},
        ]

        if query.filter_criteria:
            for k, v in query.filter_criteria.items():
                must_clauses.append({"key": k, "match": {"value": v}})

        search_body: dict[str, Any] = {
            "vector": query.query_vector,
            "limit": query.limit,
            "filter": {"must": must_clauses},
            "with_payload": True,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/collections/{collection_name}/points/search",
                headers=self.headers,
                json=search_body,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_items: list[dict[str, Any]] = data.get("result", [])
        return [
            VectorSearchResult(
                id=UUID(str(item["id"])),
                score=float(item.get("score", 0.0)),
                payload=item.get("payload", {}) or {},
            )
            for item in raw_items
        ]

    async def delete_document(
        self,
        collection_name: str,
        org_id: UUID,
        workspace_id: UUID,
        doc_id: UUID,
    ) -> None:
        """Delete vectors matching document within workspace."""
        delete_filter = {
            "filter": {
                "must": [
                    {"key": "org_id", "match": {"value": str(org_id)}},
                    {"key": "workspace_id", "match": {"value": str(workspace_id)}},
                    {"key": "doc_id", "match": {"value": str(doc_id)}},
                ]
            }
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.base_url}/collections/{collection_name}/points/delete?wait=true",
                headers=self.headers,
                json=delete_filter,
            )
            resp.raise_for_status()
