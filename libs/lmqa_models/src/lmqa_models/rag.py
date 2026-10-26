"""RAG domain models and retrieval ledger per Master §9.4 and §11."""

from __future__ import annotations

import hashlib
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChunkMetadata(BaseModel):
    """Metadata describing a chunk's document provenance."""

    model_config = ConfigDict(frozen=True)

    doc_id: UUID = Field(description="Document identity")
    doc_version: int = Field(default=1, description="Document version")
    ordinal: int = Field(default=0, description="Chunk ordinal index")
    title: str = Field(default="", description="Document title or filename")
    page: str = Field(default="1", description="Page or page range")
    section: str = Field(default="", description="Section, heading or clause name")
    kind: str = Field(default="clause", description="Chunk structural kind")


class Chunk(BaseModel):
    """A searchable text chunk with tenant isolation metadata."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID = Field(description="Chunk unique ID")
    org_id: UUID = Field(description="Organization isolation ID")
    workspace_id: UUID = Field(description="Workspace isolation boundary")
    metadata: ChunkMetadata = Field(description="Document provenance metadata")
    text: str = Field(description="Raw text content of the chunk")
    token_count: int = Field(description="Approximate token count")
    content_hash: str = Field(description="SHA-256 hash of chunk text")

    @classmethod
    def create(
        cls,
        chunk_id: UUID,
        org_id: UUID,
        workspace_id: UUID,
        metadata: ChunkMetadata,
        text: str,
    ) -> Chunk:
        """Create a Chunk with computed hash and token count."""
        chash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        # Fast whitespace-based token estimate
        tokens = max(1, len(text.split()))
        return cls(
            chunk_id=chunk_id,
            org_id=org_id,
            workspace_id=workspace_id,
            metadata=metadata,
            text=text,
            token_count=tokens,
            content_hash=chash,
        )


class RetrievalAlias(BaseModel):
    """A request-local alias mapping for a retrieved chunk (Master §9.4)."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(description="Request-local alias e.g. chunk_1")
    chunk_id: UUID = Field(description="Underlying global chunk ID")
    doc_name: str = Field(description="Source document name")
    page: str = Field(description="Page range")
    section: str = Field(description="Section heading")
    text: str = Field(description="Decrypted chunk text")
    content_hash: str = Field(description="SHA-256 hash of chunk text")
    score: float = Field(default=0.0, description="Relevance / fusion score")
    dropped: bool = Field(default=False, description="Whether dropped during token trimming")
    drop_reason: str | None = Field(default=None, description="Reason if dropped")


class RetrievalRecord(BaseModel):
    """Immutable record of chunks retrieved for a query (Master §9.4)."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(description="Unique query request ID")
    org_id: UUID = Field(description="Organization ID")
    workspace_id: UUID = Field(description="Workspace ID")
    user_id: str = Field(description="Requesting user ID")
    scope_hash: str = Field(description="Resolved access scope hash")
    query: str = Field(description="User query string")
    aliases: list[RetrievalAlias] = Field(
        default_factory=list[RetrievalAlias], description="Candidate aliases"
    )

    def alias_map(self) -> dict[str, RetrievalAlias]:
        """Return lookup map of active aliases."""
        return {a.alias: a for a in self.aliases if not a.dropped}


class SentenceVerdict(BaseModel):
    """Validation verdict for a single generated sentence (Master §11.6)."""

    model_config = ConfigDict(frozen=True)

    sentence: str = Field(description="Sentence evaluated")
    passed: bool = Field(description="Whether all V1-V8 checks passed")
    cited_aliases: list[str] = Field(default_factory=list[str], description="Cited chunk aliases")
    failed_checks: list[str] = Field(default_factory=list[str], description="Failed check IDs")
    reason: str = Field(default="", description="Explanatory verdict reason")


class CitationItem(BaseModel):
    """Resolved citation in the final answer bibliography (Master §11.5)."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(description="Cited alias e.g. chunk_1")
    doc_name: str = Field(description="Source document name")
    page: str = Field(description="Page range")
    section: str = Field(description="Section heading")
    quote_excerpt: str = Field(default="", description="Relevant excerpt for verification")


class RAGResponse(BaseModel):
    """Final gated RAG query response."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(description="Query request ID")
    query: str = Field(description="Original user query")
    answer: str = Field(description="Sentence-gated verified answer text")
    verdicts: list[SentenceVerdict] = Field(
        default_factory=list[SentenceVerdict], description="Per-sentence verdicts"
    )
    citations: list[CitationItem] = Field(
        default_factory=list[CitationItem], description="Resolved citations"
    )
    refusal: bool = Field(default=False, description="Whether answer is a canonical refusal")
