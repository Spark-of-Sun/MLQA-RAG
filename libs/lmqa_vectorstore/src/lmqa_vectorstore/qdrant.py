"""Qdrant behind a filtering wrapper (blueprint 10.5, D16, G5.1, G5.4, G5.8).

The only module that holds a Qdrant client (import-linter contract). Two classes, two keys:

  VectorReader  read-only key (retrieval). Every query takes a `VectorScope` built from the resolved principal and
                turns it into a filter that always contains `org_id` and `workspace_id`; there is no unfiltered
                query method.
  VectorWriter  read-write key (ingestion, indexer, reconciler). Upserts, payload updates and deletes also require
                `org_id` and `workspace_id` in their selector.

PostgreSQL stays the final authority: the filter is a superset of row-level security (it narrows for recall and
speed), and retrieval cross-checks every hit under RLS before use, so a stale payload can only hide a chunk, never
reveal one (G5.8).

The filter mirrors the access decision (5.4, rules 1 to 8 only): must org and workspace; must_not walled matters;
should of (owner = me), (visibility = matter and admin), (matter in my grants with tier <= ceiling), (matter in my
active emergency exceptions with tier <= cap), (visibility = private and admin with break-glass). The MVP clauses
for visibility `workspace` and named shares were removed with rules 7a and 7b (DEV-14). Large grant sets (more than
`INLINE_MATTERS`) use the over-fetch path: the grant clause is dropped from the filter (so the filter stays a
superset) and RLS removes the rest (G5.9).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient, models

COLLECTION = "lmqa_chunks"
DENSE = "dense"
SPARSE = "sparse"
INLINE_MATTERS = 256
_NAMESPACE = uuid.UUID("6f0e3b9a-6e2d-4c34-9a5e-6c1b6a2d7f10")


def point_id(chunk_id: str, version: int) -> str:
    """Deterministic per chunk and version, so a re-run upserts instead of duplicating (G4.7)."""
    return str(uuid.uuid5(_NAMESPACE, f"{chunk_id}:{version}"))


@dataclass(frozen=True)
class VectorScope:
    """What the caller may see, from PostgreSQL (never from token claims)."""

    org_id: str
    workspace_id: str
    user_id: str
    role: str  # admin | tenant
    walled_matters: frozenset[str] = frozenset()
    grants: tuple[tuple[str, int], ...] = ()  # (matter, max tier)
    emergency: tuple[tuple[str, int], ...] = ()  # (matter, tier cap <= 3)
    break_glass: bool = False


@dataclass
class ChunkPoint:
    chunk_id: str
    document_id: str
    version: int
    org_id: str
    workspace_id: str
    owner_id: str
    visibility: str
    matter_id: str | None
    tier: int
    dense: list[float]
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)
    embedding_version: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "version": self.version,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "owner_id": self.owner_id,
            "visibility": self.visibility,
            "matter_id": self.matter_id,
            "tier": self.tier,
            "embedding_version": self.embedding_version,
        }


def _match(key: str, value: Any) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _any(key: str, values: Iterable[Any]) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchAny(any=list(values)))


def build_filter(scope: VectorScope) -> models.Filter:
    if not scope.org_id or not scope.workspace_id or scope.role not in {"admin", "tenant"}:
        raise ValueError("a vector query needs an active admin or tenant principal")
    should: list[models.Condition] = [_match("owner_id", scope.user_id)]
    if scope.role == "admin":
        should.append(_match("visibility", "matter"))
        if scope.break_glass:
            should.append(_match("visibility", "private"))
    else:
        if len(scope.grants) > INLINE_MATTERS:
            should.append(_match("visibility", "matter"))  # over-fetch path; RLS decides (G5.9)
        else:
            for matter, ceiling in scope.grants:
                should.append(
                    models.Filter(
                        must=[
                            _match("visibility", "matter"),
                            _match("matter_id", matter),
                            models.FieldCondition(key="tier", range=models.Range(lte=ceiling)),
                        ]
                    )
                )
        for matter, cap in scope.emergency:
            should.append(
                models.Filter(
                    must=[
                        _match("visibility", "matter"),
                        _match("matter_id", matter),
                        models.FieldCondition(key="tier", range=models.Range(lte=min(cap, 3))),
                    ]
                )
            )
    must_not: list[models.Condition] = []
    if scope.walled_matters:
        must_not.append(_any("matter_id", sorted(scope.walled_matters)))
    return models.Filter(
        must=[_match("org_id", scope.org_id), _match("workspace_id", scope.workspace_id)],
        should=should,
        must_not=must_not or None,
    )


def _selector(
    org_id: str, workspace_id: str, extra: Sequence[models.Condition] = ()
) -> models.FilterSelector:
    if not org_id or not workspace_id:
        raise ValueError("org_id and workspace_id are required")
    return models.FilterSelector(
        filter=models.Filter(
            must=[_match("org_id", org_id), _match("workspace_id", workspace_id), *extra]
        )
    )


class VectorReader:
    def __init__(self, url: str, read_only_key: str, *, collection: str = COLLECTION) -> None:
        self._client = QdrantClient(url=url, api_key=read_only_key, timeout=10, prefer_grpc=False)
        self.collection = collection

    def hybrid(
        self,
        scope: VectorScope,
        *,
        dense: list[float] | None,
        sparse: tuple[list[int], list[float]] | None,
        limit: int = 100,
    ) -> list[tuple[str, float]]:
        """Fused dense + sparse search (Qdrant Query API, reciprocal rank fusion) inside the scope filter."""
        flt = build_filter(scope)
        prefetch = []
        if dense is not None:
            prefetch.append(models.Prefetch(query=dense, using=DENSE, limit=limit, filter=flt))
        if sparse is not None and sparse[0]:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(indices=sparse[0], values=sparse[1]),
                    using=SPARSE,
                    limit=limit,
                    filter=flt,
                )
            )
        if not prefetch:
            return []
        result = self._client.query_points(
            self.collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            query_filter=flt,
            with_payload=["chunk_id"],
        )
        return [(str(p.payload["chunk_id"]), float(p.score)) for p in result.points if p.payload]


class VectorWriter:
    def __init__(
        self, url: str, read_write_key: str, *, collection: str = COLLECTION, dense_size: int = 768
    ) -> None:
        self._client = QdrantClient(url=url, api_key=read_write_key, timeout=30, prefer_grpc=False)
        self.collection = collection
        self._size = dense_size

    def ensure_collection(self) -> None:
        if self._client.collection_exists(self.collection):
            return
        self._client.create_collection(
            self.collection,
            vectors_config={
                DENSE: models.VectorParams(size=self._size, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
            hnsw_config=models.HnswConfigDiff(
                payload_m=16, m=0
            ),  # per-tenant HNSW graphs (tiered multitenancy)
        )
        for key, schema in [
            ("org_id", models.KeywordIndexParams(type="keyword", is_tenant=True)),
            ("workspace_id", models.KeywordIndexParams(type="keyword", is_tenant=True)),
            ("document_id", "keyword"),
            ("owner_id", "keyword"),
            ("visibility", "keyword"),
            ("matter_id", "keyword"),
            ("chunk_id", "keyword"),
            ("tier", "integer"),
        ]:
            self._client.create_payload_index(self.collection, key, field_schema=schema)

    def upsert(self, points: list[ChunkPoint]) -> None:
        if not points:
            return
        for p in points:
            if not p.org_id or not p.workspace_id:
                raise ValueError("every point needs org_id and workspace_id")
        structs = []
        for p in points:
            vectors: dict[str, Any] = {DENSE: p.dense}
            if p.sparse_indices:
                vectors[SPARSE] = models.SparseVector(
                    indices=p.sparse_indices, values=p.sparse_values
                )
            structs.append(
                models.PointStruct(
                    id=point_id(p.chunk_id, p.version), vector=vectors, payload=p.payload()
                )
            )
        self._client.upsert(self.collection, points=structs, wait=True)

    def set_payload(
        self, org_id: str, workspace_id: str, document_id: str, payload: dict[str, Any]
    ) -> None:
        """Visibility, matter, tier or owner changed in PostgreSQL (outbox, 10.6)."""
        allowed = {"visibility", "matter_id", "tier", "owner_id"}
        if not set(payload) <= allowed:
            raise ValueError(f"only {sorted(allowed)} may change in place")
        self._client.set_payload(
            self.collection,
            payload=payload,
            points=_selector(org_id, workspace_id, [_match("document_id", document_id)]),
            wait=True,
        )

    def delete_document(self, org_id: str, workspace_id: str, document_id: str) -> None:
        self._client.delete(
            self.collection,
            points_selector=_selector(org_id, workspace_id, [_match("document_id", document_id)]),
            wait=True,
        )

    def delete_points(self, org_id: str, workspace_id: str, point_ids: list[str]) -> None:
        if point_ids:
            self._client.delete(
                self.collection,
                points_selector=_selector(
                    org_id, workspace_id, [models.HasIdCondition(has_id=point_ids)]
                ),
                wait=True,
            )

    def scroll_workspace(
        self, org_id: str, workspace_id: str
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        """(point id, payload) for every point of one workspace; the reconciler compares these with PostgreSQL."""
        offset = None
        flt = _selector(org_id, workspace_id).filter
        while True:
            points, offset = self._client.scroll(
                self.collection,
                scroll_filter=flt,
                limit=512,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                yield str(p.id), dict(p.payload or {})
            if offset is None:
                return
