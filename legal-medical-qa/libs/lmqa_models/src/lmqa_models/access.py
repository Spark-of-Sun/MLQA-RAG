"""The document access decision (doc section 5.4) as a pure function.

The PostgreSQL policies, the vector filter builder and the test oracle all implement exactly
this order. ``decide`` is the oracle used by the Stage 1 differential test (G1.4): RLS results
must equal this function's answer for every generated scenario.

A rule earlier in the order wins over every later rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Final
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

EMERGENCY_TIER_CAP: Final = 3
"""Tier 4 (restricted) is never reachable through emergency access (doc 5.5, 5.7)."""


class Role(StrEnum):
    """The three roles. Roles never change in v1 (doc 5.1)."""

    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    TENANT = "tenant"


class Visibility(StrEnum):
    """Document visibility: owner only, or shared to a matter."""

    PRIVATE = "private"
    MATTER = "matter"


class Tier(IntEnum):
    """Confidentiality tiers (doc 5.5)."""

    INTERNAL = 1
    CONFIDENTIAL = 2
    PRIVILEGED_OR_PHI = 3
    RESTRICTED = 4


@dataclass(frozen=True, slots=True)
class Grant:
    """A tenant's grant on one matter with a tier ceiling and optional expiry."""

    max_tier: int
    expires_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        """Return True if the grant has not expired at ``now``."""
        return self.expires_at is None or self.expires_at > now


@dataclass(frozen=True, slots=True)
class AccessContext:
    """Everything the decision needs about the caller. Built from the database, never the client."""

    user_id: UUID
    role: Role
    now: datetime
    membership_active: bool = True
    workspace_active: bool = True
    org_active: bool = True
    walls: frozenset[UUID] = frozenset()
    grants: dict[UUID, Grant] = field(default_factory=dict[UUID, Grant])
    emergency: dict[UUID, datetime] = field(default_factory=dict[UUID, datetime])
    admin_can_read_private: bool = False
    break_glass_active: bool = False


@dataclass(frozen=True, slots=True)
class Document:
    """The access-relevant fields of a document or chunk."""

    owner_user_id: UUID
    visibility: Visibility
    tier: int
    matter_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """The verdict and the rule number that produced it (1 to 8)."""

    allow: bool
    rule: int
    read_only: bool = False
    """True when the allow carries read and query only, no export (rules 6 and 7)."""


type Rule = Callable[[AccessContext, Document], Decision | None]


def _rule1_inactive(ctx: AccessContext, _doc: Document) -> Decision | None:
    if not (ctx.membership_active and ctx.workspace_active and ctx.org_active):
        return Decision(allow=False, rule=1)
    return None


def _rule2_wall(ctx: AccessContext, doc: Document) -> Decision | None:
    if doc.matter_id is not None and doc.matter_id in ctx.walls:
        return Decision(allow=False, rule=2)
    return None


def _rule3_owner(ctx: AccessContext, doc: Document) -> Decision | None:
    if ctx.role in {Role.TENANT, Role.ADMIN} and doc.owner_user_id == ctx.user_id:
        return Decision(allow=True, rule=3)
    return None


def _rule4_admin_matter(ctx: AccessContext, doc: Document) -> Decision | None:
    if ctx.role is Role.ADMIN and doc.visibility is Visibility.MATTER:
        return Decision(allow=True, rule=4)
    return None


def _rule5_grant(ctx: AccessContext, doc: Document) -> Decision | None:
    if ctx.role is not Role.TENANT or doc.visibility is not Visibility.MATTER:
        return None
    if doc.matter_id is None:
        return None
    grant = ctx.grants.get(doc.matter_id)
    if grant is not None and grant.is_active(ctx.now) and grant.max_tier >= doc.tier:
        return Decision(allow=True, rule=5)
    return None


def _rule6_emergency(ctx: AccessContext, doc: Document) -> Decision | None:
    if ctx.role is not Role.TENANT or doc.visibility is not Visibility.MATTER:
        return None
    if doc.matter_id is None:
        return None
    expires = ctx.emergency.get(doc.matter_id)
    if expires is not None and expires > ctx.now and doc.tier <= EMERGENCY_TIER_CAP:
        return Decision(allow=True, rule=6, read_only=True)
    return None


def _rule7_break_glass(ctx: AccessContext, doc: Document) -> Decision | None:
    if (
        ctx.role is Role.ADMIN
        and doc.visibility is Visibility.PRIVATE
        and ctx.admin_can_read_private
        and ctx.break_glass_active
    ):
        return Decision(allow=True, rule=7, read_only=True)
    return None


RULES: Final[tuple[Rule, ...]] = (
    _rule1_inactive,
    _rule2_wall,
    _rule3_owner,
    _rule4_admin_matter,
    _rule5_grant,
    _rule6_emergency,
    _rule7_break_glass,
)


def decide(ctx: AccessContext, doc: Document) -> Decision:
    """Return the access decision for ``ctx`` on ``doc``.

    Super Admins and operators never reach this table: they have no policy on content tables,
    so the decision for the ``super_admin`` role is always a deny here (rule 8).
    """
    if ctx.role is Role.SUPER_ADMIN:
        return Decision(allow=False, rule=8)
    for rule in RULES:
        verdict = rule(ctx, doc)
        if verdict is not None:
            return verdict
    return Decision(allow=False, rule=8)
