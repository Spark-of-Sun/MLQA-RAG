"""Tests for core models."""

from uuid import uuid4

import pytest
from lmqa_models.core import DocumentLifecycleState, TenantContext, UserRole


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
