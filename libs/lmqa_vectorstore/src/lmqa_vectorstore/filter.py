"""Vector filtering and payload isolation (Owned by Lucas Weber)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


class VectorFilterBuilder:
    """Constructs mandatory isolation filter clauses for Qdrant queries."""

    @staticmethod
    def build_workspace_filter(org_id: UUID, workspace_id: UUID) -> dict[str, Any]:
        """Build mandatory Qdrant must-match payload filter for workspace isolation."""
        return {
            "must": [
                {"key": "org_id", "match": {"value": str(org_id)}},
                {"key": "workspace_id", "match": {"value": str(workspace_id)}},
            ]
        }
