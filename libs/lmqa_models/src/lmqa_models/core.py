"""Core domain models for LMQA system."""

from __future__ import annotations

import os
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserRole(StrEnum):
    """User authorization roles per authz-matrix."""

    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    LEGAL_REVIEWER = "legal_reviewer"
    MEDICAL_REVIEWER = "medical_reviewer"
    MEMBER = "member"
    AUDITOR = "auditor"
    OPERATOR = "operator"


class DocumentLifecycleState(StrEnum):
    """Lifecycle state machine states per Master §6."""

    UPLOADING = "uploading"
    SCANNING = "scanning"
    PARSING = "parsing"
    CHUNKING = "chunking"
    INDEXED = "indexed"
    AVAILABLE = "available"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"
    PURGED = "purged"
    REJECTED = "rejected"


class TenantContext(BaseModel):
    """Multi-tenant isolation context verified by services."""

    model_config = ConfigDict(frozen=True)

    org_id: UUID = Field(description="Organization isolation ID")
    workspace_id: UUID = Field(description="Workspace isolation boundary")
    user_id: str = Field(description="Auth0 subject ID")
    role: UserRole = Field(description="Active role in workspace")


class LLMConfig(BaseModel):
    """Configuration for LLM generation, reasoning budgets, and embedding models."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(default="google", description="LLM provider name")
    model: str = Field(default="gemini-3.8-flash", description="Model identifier")
    thinking_budget: str = Field(default="high", description="Reasoning thinking budget")
    api_key: str = Field(default="", description="API key for model access")
    test_budget_usd: float = Field(default=0.0, description="Spend cap budget in USD")
    embedding_model: str = Field(default="bge-m3", description="Embedding model name")
    rerank_model: str = Field(default="bge-reranker-v2-m3", description="Reranker model name")
    nli_model_hash: str = Field(default="", description="NLI model checkpoint hash")

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Construct LLM configuration from environment variables per .env.example."""
        return cls(
            provider=os.getenv("LLM_PROVIDER", "google"),
            model=os.getenv("LLM_MODEL", "gemini-3.8-flash"),
            thinking_budget=os.getenv("LLM_THINKING_BUDGET", "high"),
            api_key=os.getenv("GEMINI_API_KEY", os.getenv("LLM_API_KEY_DEFAULT", "")),
            test_budget_usd=float(os.getenv("LLM_TEST_BUDGET_USD", "0")),
            embedding_model=os.getenv("EMBEDDING_MODEL", "bge-m3"),
            rerank_model=os.getenv("RERANK_MODEL", "bge-reranker-v2-m3"),
            nli_model_hash=os.getenv("NLI_MODEL_HASH", ""),
        )
