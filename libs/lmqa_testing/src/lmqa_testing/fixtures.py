"""Test fixtures and context helpers (Owned by Hana Sato)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class MockTenantFixture:
    """Real deterministic test context for multi-tenant isolation runs."""

    org_id: UUID
    workspace_id: UUID
    user_id: str

    @classmethod
    def create_isolated_context(cls) -> MockTenantFixture:
        """Create random UUIDs representing an isolated test organization."""
        return cls(
            org_id=uuid4(),
            workspace_id=uuid4(),
            user_id=f"auth0|{uuid4().hex[:12]}",
        )
