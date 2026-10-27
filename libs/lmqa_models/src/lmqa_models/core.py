"""Core domain models for LMQA system."""

from __future__ import annotations

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
