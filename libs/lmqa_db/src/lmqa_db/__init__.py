"""LMQA Database and RLS scoped context library."""

from __future__ import annotations

from lmqa_db.context import (
    PARAM_ORG_ID,
    PARAM_ROLE,
    PARAM_USER_ID,
    PARAM_WORKSPACE_ID,
    TenantContext,
    build_reset_local_statements,
    build_set_local_statements,
    tenant_scope,
)
from lmqa_db.pool import DatabaseConfig, create_engine_pool
from lmqa_db.self_test import (
    assert_fail_closed_environment,
    check_table_rls_force_rule,
)

__all__ = [
    "PARAM_ORG_ID",
    "PARAM_ROLE",
    "PARAM_USER_ID",
    "PARAM_WORKSPACE_ID",
    "DatabaseConfig",
    "TenantContext",
    "assert_fail_closed_environment",
    "build_reset_local_statements",
    "build_set_local_statements",
    "check_table_rls_force_rule",
    "create_engine_pool",
    "tenant_scope",
]
