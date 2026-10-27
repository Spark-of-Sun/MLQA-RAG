"""Data structures for ingestion requests and targets."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentTarget(BaseModel):
    """Document identity and scope targeting."""

    model_config = ConfigDict(frozen=True)

    doc_id: UUID = Field(description="Document identity")
    org_id: UUID = Field(description="Organization ID")
    workspace_id: UUID = Field(description="Workspace ID")
    title: str = Field(default="", description="Document title")
    doc_version: int = Field(default=1, description="Document version number")


class IngestionRequest(BaseModel):
    """Encapsulates input parameters for document processing."""

    model_config = ConfigDict(frozen=True)

    target: DocumentTarget = Field(description="Document target metadata")
    raw_data: bytes = Field(description="Raw file content")
    declared_content_type: str = Field(description="Declared MIME content type")
    expected_sha256: str | None = Field(default=None, description="Optional expected checksum")
