"""Tests for core models."""

from uuid import uuid4

import pytest
from lmqa_models.core import DocumentLifecycleState, LLMConfig, TenantContext, UserRole


@pytest.mark.stage0
@pytest.mark.unit
def test_tenant_context_valid() -> None:
    """Verify TenantContext can be instantiated with valid types at runtime."""
    org_id = uuid4()
    workspace_id = uuid4()
    ctx = TenantContext(
        org_id=org_id,
        workspace_id=workspace_id,
        user_id="auth0|usr_123",
        role=UserRole.MEMBER,
    )
    assert ctx.org_id == org_id
    assert ctx.workspace_id == workspace_id
    assert ctx.user_id == "auth0|usr_123"
    assert ctx.role == UserRole.MEMBER
    assert ctx.role == "member"


@pytest.mark.stage0
@pytest.mark.unit
def test_document_lifecycle_state_values() -> None:
    """Verify DocumentLifecycleState enum values."""
    assert DocumentLifecycleState.AVAILABLE == "available"
    assert DocumentLifecycleState.SCANNING == "scanning"


@pytest.mark.stage0
@pytest.mark.unit
def test_llm_config_defaults() -> None:
    """Verify LLMConfig model reflects .env.example Google Gemini settings."""
    cfg = LLMConfig.from_env()
    assert cfg.provider == "google"
    assert cfg.model == "gemini-3.8-flash"
    assert cfg.thinking_budget == "high"
    assert cfg.embedding_model == "bge-m3"
    assert cfg.rerank_model == "bge-reranker-v2-m3"
