"""The Qdrant filter builder (doc 10.5, G5.1, G5.4).

Qdrant does not enforce a payload filter inside a shared collection: a missing filter is *not*
rejected (DEF-01). So this module builds the filter from a principal-derived ``VectorScope`` and
there is no way to search without one. The filter *narrows* for recall and speed; PostgreSQL RLS
stays the final authority, and retrieval cross-checks every returned ID against it.

Filter shape (doc 10.5):

* Always: ``org_id`` and ``workspace_id`` equal the principal's, and ``is_current``.
* ``must_not`` the walled matters (a wall beats ownership, grants, admin and emergency access).
* Tenant: owned documents, or matter-shared documents of a granted matter up to the grant's tier
  ceiling; an active emergency exception adds its matter with the tier cap of 3.
* Admin: owned documents, or any matter-shared document; private documents of others only when
  the workspace flag and an active break-glass session both allow it.
* More than ``MAX_INLINE_MATTERS`` granted matters: filter by workspace and visibility only and
  let PostgreSQL discard what is not allowed ("over-fetch and cross-check").
* If no filter can be built, the caller gets ``NoFilterError`` (HTTP 403), never an unfiltered
  search.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from qdrant_client import models

MAX_INLINE_MATTERS: Final = 256
EMERGENCY_TIER_CAP: Final = 3
_ROLES: Final = frozenset({"admin", "tenant"})


class NoFilterError(PermissionError):
    """No safe filter can be built for this principal. Answer 403; never search unfiltered."""


@dataclass(frozen=True, slots=True)
class VectorScope:
    """What a principal may reach, resolved from PostgreSQL by retrieval for each request."""

    org_id: UUID
    workspace_id: UUID
    user_id: UUID
    role: str
    grants: Mapping[UUID, int] = field(default_factory=dict[UUID, int])
    """Unexpired grants: matter to tier ceiling."""
    walled: frozenset[UUID] = frozenset()
    emergency_matters: frozenset[UUID] = frozenset()
    admin_private_read: bool = False
    """True only when the workspace flag AND an active break-glass session both hold."""
    narrow_to: frozenset[UUID] | None = None
    """Optional request narrowing. It can only reduce the result, never widen it."""


@dataclass(frozen=True, slots=True)
class BuiltFilter:
    """A filter and whether PostgreSQL must discard extra hits (large grant sets)."""

    qdrant_filter: models.Filter
    overfetch: bool


def _eq(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _any(key: str, values: list[str]) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchAny(any=values))


def _matter_tier(matter: UUID, tier: int) -> models.Filter:
    return models.Filter(
        must=[
            _eq("matter_id", str(matter)),
            _eq("visibility", "matter"),
            models.FieldCondition(key="tier", range=models.Range(lte=tier)),
        ]
    )


def build_filter(scope: VectorScope) -> BuiltFilter:
    """Build the Qdrant filter for ``scope`` or raise ``NoFilterError``."""
    if scope.role not in _ROLES:
        msg = f"no vector filter for role {scope.role!r}"
        raise NoFilterError(msg)
    must: list[models.Condition] = [
        _eq("org_id", str(scope.org_id)),
        _eq("workspace_id", str(scope.workspace_id)),
        models.FieldCondition(key="is_current", match=models.MatchValue(value=True)),
    ]
    must_not: list[models.Condition] = []
    if scope.walled:
        must_not.append(_any("matter_id", sorted(str(m) for m in scope.walled)))
    if scope.narrow_to is not None:
        must.append(_any("matter_id", sorted(str(m) for m in scope.narrow_to)))

    owner = _eq("owner_user_id", str(scope.user_id))
    access: list[models.Condition] = [owner]
    overfetch = False
    if scope.role == "admin":
        access.append(_eq("visibility", "matter"))
        if scope.admin_private_read:
            access.append(_eq("visibility", "private"))
    elif len(scope.grants) > MAX_INLINE_MATTERS:
        # Too many matters for an inline filter: filter by workspace and visibility only
        # and let Postgres decide.
        access.append(_eq("visibility", "matter"))
        overfetch = True
    else:
        access.extend(_matter_tier(m, tier) for m, tier in sorted(scope.grants.items()))
    if scope.role == "tenant" and not overfetch:
        access.extend(_matter_tier(m, EMERGENCY_TIER_CAP) for m in sorted(scope.emergency_matters))
    elif scope.role == "tenant" and scope.emergency_matters:
        overfetch = True  # emergency access is evaluated by Postgres on the over-fetched set

    must.append(models.Filter(should=access))
    return BuiltFilter(models.Filter(must=must, must_not=must_not or None), overfetch)


def filter_mentions_scope(built: models.Filter, scope: VectorScope) -> bool:
    """True if the filter pins ``org_id`` and ``workspace_id`` (checked by search and by tests)."""
    pinned: dict[str, str] = {}
    for condition in built.must or []:
        if isinstance(condition, models.FieldCondition) and isinstance(
            condition.match, models.MatchValue
        ):
            pinned[condition.key] = str(condition.match.value)
    return pinned.get("org_id") == str(scope.org_id) and pinned.get("workspace_id") == str(
        scope.workspace_id
    )
