"""Tenant Context and Scoped Session Manager for PostgreSQL RLS.

Master System Design §5.4, §19.4 & Gate G1.3, G1.7.
Enforces PgBouncer transaction-pooling safety via transaction-local (SET LOCAL)
parameters to prevent cross-tenant context leaks.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator
    from uuid import UUID

# Configuration parameter keys
PARAM_ORG_ID = "lmqa.current_tenant_id"
PARAM_WORKSPACE_ID = "lmqa.current_workspace_id"
PARAM_USER_ID = "lmqa.current_user_id"
PARAM_ROLE = "lmqa.current_user_role"


@runtime_checkable
class ExecutableSession(Protocol):
    """Protocol for database session with SQL execution capability."""

    def execute(self, statement: str) -> object:
        """Execute a raw SQL statement."""
        ...


@dataclass(frozen=True)
class TenantContext:
    """Immutable context identifying the current authenticated tenant and user."""

    org_id: UUID
    workspace_id: UUID | None = None
    user_id: UUID | None = None
    role: str | None = None

    def is_complete(self) -> bool:
        """Check if context contains full workspace execution parameters."""
        return self.workspace_id is not None and self.user_id is not None


def build_set_local_statements(ctx: TenantContext) -> list[str]:
    """Generate PostgreSQL 'SET LOCAL' statements for transaction-scoped context.

    Uses SET LOCAL so that PgBouncer transaction pooling resets context
    automatically upon COMMIT or ROLLBACK.

    Args:
        ctx: TenantContext instance.

    Returns:
        List of SQL statements to execute on transaction start.
    """
    statements = [
        f"SET LOCAL {PARAM_ORG_ID} = '{ctx.org_id}';",
    ]
    if ctx.workspace_id is not None:
        statements.append(f"SET LOCAL {PARAM_WORKSPACE_ID} = '{ctx.workspace_id}';")
    else:
        statements.append(f"SET LOCAL {PARAM_WORKSPACE_ID} = '';")

    if ctx.user_id is not None:
        statements.append(f"SET LOCAL {PARAM_USER_ID} = '{ctx.user_id}';")
    else:
        statements.append(f"SET LOCAL {PARAM_USER_ID} = '';")

    if ctx.role is not None:
        statements.append(f"SET LOCAL {PARAM_ROLE} = '{ctx.role}';")
    else:
        statements.append(f"SET LOCAL {PARAM_ROLE} = '';")

    return statements


def build_reset_local_statements() -> list[str]:
    """Generate PostgreSQL statements to clear transaction-scoped context."""
    return [
        f"SET LOCAL {PARAM_ORG_ID} = '';",
        f"SET LOCAL {PARAM_WORKSPACE_ID} = '';",
        f"SET LOCAL {PARAM_USER_ID} = '';",
        f"SET LOCAL {PARAM_ROLE} = '';",
    ]


@contextmanager
def tenant_scope(
    session: ExecutableSession | object, ctx: TenantContext
) -> Generator[TenantContext]:
    """Scoped context manager for transaction-local tenant context.

    If session supports execute(), runs SET LOCAL statements.
    """
    statements = build_set_local_statements(ctx)
    if isinstance(session, ExecutableSession):
        for stmt in statements:
            session.execute(stmt)
    try:
        yield ctx
    finally:
        reset_stmts = build_reset_local_statements()
        if isinstance(session, ExecutableSession):
            for stmt in reset_stmts:
                session.execute(stmt)
