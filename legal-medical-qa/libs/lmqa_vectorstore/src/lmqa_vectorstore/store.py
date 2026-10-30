"""Qdrant access (doc 10.5). The only module that holds a Qdrant client.

* ``VectorReader`` uses the read-only API key (retrieval). It has one query method and that
  method requires a ``VectorScope``: there is no unfiltered variant.
* ``VectorWriter`` uses the read-write key (ingestion, indexer, reconciler). Delete and payload
  update calls also require ``org_id`` and ``workspace_id``; nothing accepts a raw filter, and
  points are never fetched by user-supplied ID.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models

from lmqa_vectorstore.filters import NoFilterError, VectorScope, build_filter, filter_mentions_scope

if TYPE_CHECKING:
    from collections.abc import Sequence

DENSE: Final = "dense"
SPARSE: Final = "sparse"
PAYLOAD_VERSION_KEY: Final = "payload_version"
PREFETCH_LIMIT: Final = 100
_PAGE: Final = 512
_LOOPBACK: Final = frozenset({"127.0.0.1", "localhost", "::1"})


def _client(url: str, api_key: str) -> AsyncQdrantClient:
    """Create a client; the API key crosses plain HTTP only on loopback, else TLS is required."""
    parts = urlsplit(url)
    loopback = (parts.hostname or "") in _LOOPBACK
    if parts.scheme != "https" and not loopback:
        msg = "the Qdrant URL must use https unless it is a loopback address"
        raise ValueError(msg)
    with warnings.catch_warnings():
        if loopback:
            warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        return AsyncQdrantClient(url=url, api_key=api_key, prefer_grpc=False)


@dataclass(frozen=True, slots=True)
class SparseVec:
    """A sparse term vector (BM25-style): parallel index and weight lists."""

    indices: list[int]
    values: list[float]


@dataclass(frozen=True, slots=True)
class ChunkPoint:
    """One chunk to index. The point ID is the chunk ID; the payload carries only access fields."""

    chunk_id: UUID
    dense: list[float]
    sparse: SparseVec
    org_id: UUID
    workspace_id: UUID
    doc_id: UUID
    doc_version: int
    owner_user_id: UUID
    matter_id: UUID | None
    visibility: str
    tier: int
    is_current: bool = True
    payload_version: int = 1

    def payload(self) -> dict[str, str | int | bool]:
        """Access fields only. Text never goes into the vector store payload."""
        data: dict[str, str | int | bool] = {
            "org_id": str(self.org_id),
            "workspace_id": str(self.workspace_id),
            "doc_id": str(self.doc_id),
            "doc_version": self.doc_version,
            "owner_user_id": str(self.owner_user_id),
            "visibility": self.visibility,
            "tier": self.tier,
            "is_current": self.is_current,
            PAYLOAD_VERSION_KEY: self.payload_version,
        }
        if self.matter_id is not None:
            data["matter_id"] = str(self.matter_id)
        return data


@dataclass(frozen=True, slots=True)
class Hit:
    """A search hit: a chunk ID and its fused score. Text always comes from PostgreSQL."""

    chunk_id: UUID
    score: float


class VectorReader:
    """Retrieval's read-only view of the vector store."""

    def __init__(self, url: str, read_only_key: str, collection: str) -> None:
        """Connect with the read-only API key."""
        self._client = _client(url, read_only_key)
        self._collection = collection

    async def aclose(self) -> None:
        """Close the connection."""
        await self._client.close()

    async def search(
        self, scope: VectorScope, dense: Sequence[float], sparse: SparseVec, limit: int = 100
    ) -> tuple[list[Hit], bool]:
        """Hybrid dense + sparse search fused with reciprocal rank fusion, under ``scope``.

        Returns ``(hits, overfetch)``; when ``overfetch`` is true PostgreSQL must discard hits
        the caller may not read before anything is used.

        Raises:
            NoFilterError: no safe filter can be built; the caller answers 403.
        """
        built = build_filter(scope)
        if not filter_mentions_scope(built.qdrant_filter, scope):  # defense in depth
            msg = "refusing to search: the filter does not pin organization and workspace"
            raise NoFilterError(msg)
        flt = built.qdrant_filter
        response = await self._client.query_points(
            collection_name=self._collection,
            prefetch=[
                models.Prefetch(query=list(dense), using=DENSE, limit=PREFETCH_LIMIT, filter=flt),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                    using=SPARSE,
                    limit=PREFETCH_LIMIT,
                    filter=flt,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=flt,
            limit=limit,
            with_payload=False,
        )
        return [Hit(UUID(str(p.id)), float(p.score)) for p in response.points], built.overfetch


class VectorWriter:
    """Ingestion's read-write view. Every mutation is pinned to an organization and workspace."""

    def __init__(self, url: str, read_write_key: str, collection: str) -> None:
        """Connect with the read-write API key."""
        self._client = _client(url, read_write_key)
        self._collection = collection

    async def aclose(self) -> None:
        """Close the connection."""
        await self._client.close()

    async def ensure_collection(self, dense_size: int) -> None:
        """Create the collection with named dense and sparse vectors and tenant-indexed payloads."""
        exists = await self._client.collection_exists(self._collection)
        if not exists:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    DENSE: models.VectorParams(size=dense_size, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={
                    SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
        tenant = models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD, is_tenant=True)
        keyword = models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD)
        for name, schema in (
            ("workspace_id", tenant),
            ("org_id", keyword),
            ("owner_user_id", keyword),
            ("matter_id", keyword),
            ("visibility", keyword),
            ("doc_id", keyword),
            ("tier", models.PayloadSchemaType.INTEGER),
            ("is_current", models.PayloadSchemaType.BOOL),
        ):
            await self._client.create_payload_index(self._collection, name, field_schema=schema)

    async def upsert(self, points: Sequence[ChunkPoint]) -> None:
        """Index chunks. Quarantined chunks must never be passed in (the indexer enforces it)."""
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=str(p.chunk_id),
                    vector={
                        DENSE: p.dense,
                        SPARSE: models.SparseVector(
                            indices=p.sparse.indices, values=p.sparse.values
                        ),
                    },
                    payload=p.payload(),
                )
                for p in points
            ],
            wait=True,
        )

    def _doc_filter(self, org_id: UUID, workspace_id: UUID, doc_id: UUID) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(key="org_id", match=models.MatchValue(value=str(org_id))),
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=str(workspace_id))
                ),
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=str(doc_id))),
            ]
        )

    async def set_access_payload(
        self, org_id: UUID, workspace_id: UUID, doc_id: UUID, fields: dict[str, str | int | bool]
    ) -> None:
        """Update access fields after a visibility, matter, tier or owner change (indexer)."""
        allowed = {
            "visibility",
            "tier",
            "matter_id",
            "owner_user_id",
            "is_current",
            PAYLOAD_VERSION_KEY,
        }
        if not set(fields) <= allowed:
            msg = f"refusing to set non-access payload fields: {sorted(set(fields) - allowed)}"
            raise ValueError(msg)
        await self._client.set_payload(
            collection_name=self._collection,
            payload=fields,
            points=self._doc_filter(org_id, workspace_id, doc_id),
            wait=True,
        )

    async def delete_document(self, org_id: UUID, workspace_id: UUID, doc_id: UUID) -> None:
        """Delete every vector of one document."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(
                filter=self._doc_filter(org_id, workspace_id, doc_id)
            ),
            wait=True,
        )

    async def delete_workspace(self, org_id: UUID, workspace_id: UUID) -> None:
        """Delete every vector of one workspace (workspace or organization removal)."""
        flt = models.Filter(
            must=[
                models.FieldCondition(key="org_id", match=models.MatchValue(value=str(org_id))),
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=str(workspace_id))
                ),
            ]
        )
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=flt),
            wait=True,
        )

    async def list_points(self, org_id: UUID, workspace_id: UUID) -> dict[UUID, int]:
        """Chunk ID to payload version for one workspace (the reconciler's view)."""
        flt = models.Filter(
            must=[
                models.FieldCondition(key="org_id", match=models.MatchValue(value=str(org_id))),
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=str(workspace_id))
                ),
            ]
        )
        found: dict[UUID, int] = {}
        offset: Any = None  # the scroll cursor type is not exported by qdrant-client
        while True:
            points, offset = await self._client.scroll(
                self._collection,
                scroll_filter=flt,
                limit=_PAGE,
                offset=offset,
                with_payload=[PAYLOAD_VERSION_KEY],
                with_vectors=False,
            )
            for p in points:
                found[UUID(str(p.id))] = int((p.payload or {}).get(PAYLOAD_VERSION_KEY, 0))
            if offset is None:
                return found

    async def drop_collection(self) -> None:
        """Remove the whole collection (tests and re-embedding swaps only)."""
        await self._client.delete_collection(self._collection)
