"""Request context for row-level security (doc 10.3).

Context is set per *transaction* with ``set_config(name, value, true)``. That is safe under
PgBouncer transaction pooling: a session-level ``SET`` would leak between requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ContextRole(StrEnum):
    """Whom a service is acting for. Policies read this through ``app_role()``."""

    SYSTEM = "system"
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TENANT = "tenant"
    RECONCILER = "reconciler"


class MissingContextError(RuntimeError):
    """Raised when code tries to run a query without a request context."""


@dataclass(frozen=True, slots=True)
class DbContext:
    """The identity a transaction runs as, from the verified context token."""

    role: ContextRole
    org_id: UUID | None = None
    workspace_id: UUID | None = None
    user_id: UUID | None = None

    @property
    def org(self) -> UUID:
        """The organization, or ``MissingContextError`` if this context has none."""
        if self.org_id is None:
            msg = "this database context has no organization"
            raise MissingContextError(msg)
        return self.org_id

    @property
    def ws(self) -> UUID:
        """The workspace, or ``MissingContextError`` if this context has none."""
        if self.workspace_id is None:
            msg = "this database context has no workspace"
            raise MissingContextError(msg)
        return self.workspace_id

    @property
    def user(self) -> UUID:
        """The user, or ``MissingContextError`` if this context has none."""
        if self.user_id is None:
            msg = "this database context has no user"
            raise MissingContextError(msg)
        return self.user_id

    def settings(self) -> dict[str, str]:
        """Return the ``app.*`` settings this context stands for (empty string when unset)."""
        return {
            "app.role": self.role.value,
            "app.org_id": str(self.org_id) if self.org_id else "",
            "app.workspace_id": str(self.workspace_id) if self.workspace_id else "",
            "app.user_id": str(self.user_id) if self.user_id else "",
        }

    def validate(self) -> None:
        """Refuse contexts that cannot identify a scope for their role."""
        if self.role is not ContextRole.SYSTEM and self.org_id is None:
            msg = f"context role {self.role.value} requires org_id"
            raise MissingContextError(msg)
        if (
            self.role in {ContextRole.ADMIN, ContextRole.TENANT, ContextRole.RECONCILER}
            and self.workspace_id is None
        ):
            msg = f"context role {self.role.value} requires workspace_id"
            raise MissingContextError(msg)
        if self.role in {ContextRole.ADMIN, ContextRole.TENANT} and self.user_id is None:
            msg = f"context role {self.role.value} requires user_id"
            raise MissingContextError(msg)
