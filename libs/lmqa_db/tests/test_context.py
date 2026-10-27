"""Tests for Scoped Session Context and Fail-Closed Verification.

Enforces Master System Design §5.4 and Gate G1.3, G1.7.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from lmqa_db import (
    PARAM_ORG_ID,
    PARAM_ROLE,
    PARAM_USER_ID,
    PARAM_WORKSPACE_ID,
    TenantContext,
    assert_fail_closed_environment,
    build_reset_local_statements,
    build_set_local_statements,
    check_table_rls_force_rule,
    tenant_scope,
)


@pytest.mark.stage0
@pytest.mark.unit
def test_tenant_context_creation() -> None:
    org_id = uuid4()
    ws_id = uuid4()
    user_id = uuid4()

    ctx = TenantContext(org_id=org_id, workspace_id=ws_id, user_id=user_id, role="admin")
    assert ctx.org_id == org_id
    assert ctx.workspace_id == ws_id
    assert ctx.user_id == user_id
    assert ctx.role == "admin"
    assert ctx.is_complete()

    partial_ctx = TenantContext(org_id=org_id)
    assert not partial_ctx.is_complete()


@pytest.mark.stage0
@pytest.mark.unit
def test_set_local_statements_generation() -> None:
    org_id = uuid4()
    ws_id = uuid4()
    user_id = uuid4()

    ctx = TenantContext(org_id=org_id, workspace_id=ws_id, user_id=user_id, role="member")
    stmts = build_set_local_statements(ctx)

    assert any(f"SET LOCAL {PARAM_ORG_ID} = '{org_id}'" in s for s in stmts)
    assert any(f"SET LOCAL {PARAM_WORKSPACE_ID} = '{ws_id}'" in s for s in stmts)
    assert any(f"SET LOCAL {PARAM_USER_ID} = '{user_id}'" in s for s in stmts)
    assert any(f"SET LOCAL {PARAM_ROLE} = 'member'" in s for s in stmts)


@pytest.mark.stage0
@pytest.mark.unit
def test_reset_local_statements_generation() -> None:
    stmts = build_reset_local_statements()
    assert len(stmts) == 4
    assert any(f"SET LOCAL {PARAM_ORG_ID} = ''" in s for s in stmts)


@pytest.mark.stage0
@pytest.mark.unit
def test_mock_session_tenant_scope() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.executed: list[str] = []

        def execute(self, stmt: str) -> None:
            self.executed.append(stmt)

    session = FakeSession()
    ctx = TenantContext(org_id=uuid4(), role="member")

    with tenant_scope(session, ctx) as active_ctx:
        assert active_ctx == ctx
        assert len(session.executed) == 4

    # Post-exit: cleanup statements executed
    assert len(session.executed) == 8


@pytest.mark.stage0
@pytest.mark.unit
def test_fail_closed_assertion() -> None:
    with pytest.raises(PermissionError, match="Fail-closed invariant violation"):
        assert_fail_closed_environment(None)

    with pytest.raises(PermissionError, match="Fail-closed invariant violation"):
        assert_fail_closed_environment("")

    assert assert_fail_closed_environment(str(uuid4())) is True


@pytest.mark.stage0
@pytest.mark.unit
def test_table_force_rls_rule() -> None:
    assert check_table_rls_force_rule(table_rls_enabled=True, table_rls_forced=True) is True
    assert check_table_rls_force_rule(table_rls_enabled=True, table_rls_forced=False) is False
    assert check_table_rls_force_rule(table_rls_enabled=False, table_rls_forced=True) is False
