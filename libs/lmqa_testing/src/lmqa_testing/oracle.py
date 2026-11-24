"""The reference oracle for the access decision (blueprint 5.4, R-4 criterion 1, G1.4).

A plain-Python statement of rules 1 to 8, in order, the first matching rule deciding. It is written independently of
the SQL in db/policies/11_access.sql and of the vector filter in lmqa_vectorstore. The MVP rules 7a (visibility
`workspace`) and 7b (`document_shares`) are deliberately absent (KD-3, DEV-14): a document with any visibility other
than `matter` or `private` falls through to rule 8. Property 1 generates at least 20,000 worlds with
`lmqa_testing.strategies` and asserts that row-level security returns exactly what `can_read` allows, for every role,
table and operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

OPERATIONS = ("read", "query", "export")
CONTENT_ROLES = frozenset(
    {"admin", "tenant"}
)  # super_admin and operator roles never read content (R-4.6)
EMERGENCY_DEPLOYMENTS = frozenset({"medical", "both"})
EMERGENCY_TIER_CEILING = 3  # an emergency exception never reaches tier 4 (R-5.4)
LIMITED_OPERATIONS = frozenset({"read", "query"})  # rules 6 and 7: no export


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str  # admin | tenant | super_admin | operator
    workspace_id: str | None  # the active workspace; None for super_admin and operators
    membership_active: bool
    workspace_active: bool
    org_active: bool
    org_kind: str = "legal"  # the deployment type: legal | medical | both


@dataclass(frozen=True)
class Document:
    id: str
    workspace_id: str
    owner_id: str
    visibility: str  # private | matter
    matter_id: str | None
    tier: int  # 1 internal, 2 confidential, 3 privileged_or_phi, 4 restricted


@dataclass
class World:
    now: datetime
    walls: set[tuple[str, str]] = field(default_factory=set)  # (user, matter), live and effective
    grants: dict[tuple[str, str], tuple[int, datetime | None]] = field(
        default_factory=dict
    )  # (user, matter) -> (max_tier, expiry or None)
    emergency: dict[tuple[str, str], tuple[int, datetime]] = field(
        default_factory=dict
    )  # (user, matter) -> (tier cap, expiry) for exceptions in state `active`
    break_glass: dict[str, datetime] = field(default_factory=dict)  # admin -> session expiry
    admin_can_read_private: dict[str, bool] = field(
        default_factory=dict
    )  # workspace -> flag (default false)
    emergency_enabled: dict[str, bool] = field(
        default_factory=dict
    )  # workspace -> `emergency_access` flag
    principals: tuple[Principal, ...] = ()  # populated by strategies.worlds()
    documents: tuple[Document, ...] = ()  # populated by strategies.worlds()


def decide(w: World, p: Principal, d: Document, op: str = "read") -> tuple[int, bool]:  # noqa: C901, PLR0911 - one linear flow, one return per rule
    """Return (number of the deciding rule, allow) for principal `p` performing `op` on document `d`."""
    if op not in OPERATIONS:
        raise ValueError(f"unknown operation {op!r}")
    # Rule 1: membership, workspace or organization not active. Roles without a content membership (super_admin,
    # operators) and documents outside the principal's active workspace have no active membership to match.
    if (
        p.role not in CONTENT_ROLES
        or not (p.membership_active and p.workspace_active and p.org_active)
        or p.workspace_id != d.workspace_id
    ):
        return 1, False
    # Rule 2: a wall on the document's matter beats everything below, ownership included.
    if d.matter_id is not None and (p.user_id, d.matter_id) in w.walls:
        return 2, False
    # Rule 3: the user owns the document.
    if d.owner_id == p.user_id:
        return 3, True
    if d.visibility == "matter" and d.matter_id is not None:
        # Rule 4: admin, visibility `matter`, all tiers.
        if p.role == "admin":
            return 4, True
        key = (p.user_id, d.matter_id)
        # Rule 5: tenant with an unexpired grant whose max_tier covers the document's tier.
        grant = w.grants.get(key)
        if grant is not None and (grant[1] is None or grant[1] > w.now) and grant[0] >= d.tier:
            return 5, True
        # Rule 6: tenant in a medical or both deployment with an active emergency exception, tier within the cap.
        exc = w.emergency.get(key)
        if (
            exc is not None
            and exc[1] > w.now
            and w.emergency_enabled.get(d.workspace_id, False)
            and p.org_kind in EMERGENCY_DEPLOYMENTS
            and d.tier <= min(exc[0], EMERGENCY_TIER_CEILING)
        ):
            return 6, op in LIMITED_OPERATIONS
    # Rule 7: admin break-glass on a private document, with the governed flag and a live session.
    if d.visibility == "private" and p.role == "admin":
        session = w.break_glass.get(p.user_id)
        if (
            w.admin_can_read_private.get(d.workspace_id, False)
            and session is not None
            and session > w.now
        ):
            return 7, op in LIMITED_OPERATIONS
    # Rule 8: anything else.
    return 8, False


def can_read(w: World, p: Principal, d: Document, op: str = "read") -> bool:
    """The §5.4 access decision: True when rules 1 to 8, first match deciding, allow `op`."""
    return decide(w, p, d, op)[1]
