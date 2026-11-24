"""Response fields of frozen MVP-only features (DEV-21, KD-13, pending Q-04).

Routes of a frozen feature carry its flag in contracts/authz-matrix.yaml, so the guard answers 404 for them. Some
frozen features are fields inside routes that stay on: profile details and usage counts in Manage members and
Manage admins. While their flag is off the gateway drops those fields before the response leaves, so the screens
cannot show them and the BFF never receives them.
"""

from __future__ import annotations

from typing import Any

from lmqa_models.contracts import feature_enabled

PROFILE_FIELDS = frozenset({"job_title", "department", "phone", "profile_updated_at"})
MEMBER_USAGE_FIELDS = frozenset(
    {
        "documents",
        "private_documents",
        "shared_with_you",
        "shared_with_them",
        "shared_with_workspace",
        "questions",
        "tokens",
        "last_question_at",
    }
)
WORKSPACE_USAGE_FIELDS = frozenset({"documents", "queries", "queries_30d"})


def _without(rows: list[dict[str, Any]], fields: frozenset[str]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k not in fields} for r in rows] if fields else rows


def member_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manage members: profile details only with `profiles`, counts only with `usage_counts`."""
    hidden: frozenset[str] = frozenset()
    if not feature_enabled("profiles"):
        hidden |= PROFILE_FIELDS
    if not feature_enabled("usage_counts"):
        hidden |= MEMBER_USAGE_FIELDS
    return _without(rows, hidden)


def admin_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manage admins: workspace document and question counts only with `usage_counts`."""
    return _without(
        rows, frozenset() if feature_enabled("usage_counts") else WORKSPACE_USAGE_FIELDS
    )
