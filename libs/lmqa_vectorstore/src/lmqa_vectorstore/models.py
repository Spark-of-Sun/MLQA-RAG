"""Data models for vector operations and search results."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VectorPoint(BaseModel):
    """A vector point representation for upsert into Qdrant."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Unique point identifier, typically chunk_id")
    vector: list[float] = Field(description="Dense vector embedding")
    payload: dict[str, Any] = Field(description="Point metadata payload containing tenant IDs")


class VectorQuery(BaseModel):
    """Encapsulated vector search query parameters."""

    model_config = ConfigDict(frozen=True)

    query_vector: list[float] = Field(description="Dense vector query")
    org_id: UUID = Field(description="Mandatory organization isolation boundary")
    workspace_id: UUID = Field(description="Mandatory workspace isolation boundary")
    limit: int = Field(default=10, description="Maximum number of candidates to return")
    filter_criteria: dict[str, Any] | None = Field(
        default=None, description="Optional extra payload filters"
    )


class VectorSearchResult(BaseModel):
    """Result item from a vector similarity search."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(description="Point identifier")
    score: float = Field(description="Similarity score")
    payload: dict[str, Any] = Field(description="Payload metadata")
