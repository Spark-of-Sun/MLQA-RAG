"""The resolved caller. Built from the database on every request, never from token claims (blueprint 8)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Membership:
    id: str
    role: str  # super_admin | admin | tenant
    status: str  # pending | active | rejected | suspended
    org_id: str
    org_name: str
    org_kind: str
    org_status: str
    workspace_id: str | None
    workspace_name: str | None
    workspace_status: str | None

    @property
    def active(self) -> bool:
        return (
            self.status == "active"
            and self.org_status == "active"
            and (self.workspace_id is None or self.workspace_status == "active")
        )


@dataclass(frozen=True)
class Principal:
    user_id: str
    sub: str
    email: str | None
    name: str | None
    membership: Membership | None

    @property
    def role(self) -> str | None:
        return self.membership.role if self.membership else None
