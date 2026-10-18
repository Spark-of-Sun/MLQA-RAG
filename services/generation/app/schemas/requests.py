from __future__ import annotations

from pydantic import BaseModel


class InputChunk(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    page: int
    section: str | None = None
    rerank_score: float | None = None


class GenerateRequest(BaseModel):
    question: str
    tenant_id: str
    chunks: list[InputChunk]
    max_prompt_tokens: int = 6000
    max_completion_tokens: int = 1024
    prompt_template_version: str | None = None


class RawGeneration(BaseModel):
    answer_text: str
    chunk_ids_in_context: list[str]
    dropped_chunk_ids: list[str] = []
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool = False


class GenerateStreamEvent(BaseModel):
    type: str  # "token" | "final" | "error"
    token: str | None = None
    final: RawGeneration | None = None
    error: str | None = None
