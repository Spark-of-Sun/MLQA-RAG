"""KeyGuard (blueprint 12.5 to 12.7): the only path to disabling or destroying an organization key.

Destroying is hard, restoring is easy:

* `authorize_destruction` refuses unless the organization is `sealed`, an `executable` governance request of kind
  `org_delete` (or `workspace_destroy`) exists with the required number of distinct approvers and distinct
  authenticators, its waiting window has elapsed, retention has ended and no legal hold exists.
* `schedule_destruction` then schedules deletion with the maximum window (30 days; 7 only for `drill`-tagged keys),
  replica first. In AWS the call is made by the `keyguard-destroyer` role, assumable only by this workflow with
  session tags carrying the approval IDs, which the key policy checks (infra/keyguard).
* `respond` is the detective control: for every key event from CloudTrail (via EventBridge) it looks for a matching
  approved record; when none exists it cancels the deletion and re-enables the key, within 60 seconds of the event.
* `lint_key_policy` fails CI when a production key's policy lets any principal other than the two named roles
  schedule deletion, disable the key or change its policy, or when a window is shorter than the minimum.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from lmqa_keys.providers import (
    DRILL_DELETION_WINDOW_DAYS,
    PRODUCTION_DELETION_WINDOW_DAYS,
    KeyProvider,
)

DESTRUCTIVE_ACTIONS = (
    "kms:ScheduleKeyDeletion",
    "kms:DisableKey",
    "kms:PutKeyPolicy",
    "kms:DeleteImportedKeyMaterial",
)
ALLOWED_DESTRUCTIVE_ROLES = ("keyguard-destroyer", "key-admin")
RESPONDER_ACTIONS = ("kms:CancelKeyDeletion", "kms:EnableKey")
WATCHED_EVENTS = (
    "ScheduleKeyDeletion",
    "DisableKey",
    "CancelKeyDeletion",
    "PutKeyPolicy",
    "DeleteImportedKeyMaterial",
    "ImportKeyMaterial",
)


class KeyGuardRefusal(PermissionError):
    """KeyGuard will not proceed; the message names the unmet condition."""


class _Conn(Protocol):
    def execute(self, query: Any, params: Any = None) -> Any: ...


@dataclass(frozen=True)
class Approval:
    approver_id: str
    authenticator_id: str
    approver_kind: str
    step_up_at: datetime


@dataclass
class DestructionPlan:
    org_id: str
    request_id: str
    key_refs: list[str]
    window_days: int
    approvals: list[Approval] = field(default_factory=list)


def authorize_destruction(
    conn: _Conn, org_id: UUID | str, request_id: UUID | str, *, now: datetime | None = None
) -> DestructionPlan:
    now = now or datetime.now(UTC)
    org = conn.execute(
        "select status, legal_hold, retention_days, deletion_requested_at from organizations where id = %s",
        [str(org_id)],
    ).fetchone()
    if not org:
        raise KeyGuardRefusal("organization not found")
    if org["status"] != "sealed":
        raise KeyGuardRefusal(f"organization is {org['status']}, not sealed")
    if org["legal_hold"]:
        raise KeyGuardRefusal("organization is under legal hold")
    held = conn.execute(
        "select 1 from workspaces where org_id = %s and legal_hold union all"
        " select 1 from documents where org_id = %s and legal_hold limit 1",
        [str(org_id), str(org_id)],
    ).fetchone()
    if held:
        raise KeyGuardRefusal("a workspace or document of the organization is under legal hold")
    req = conn.execute(
        "select kind, state, initiator_id, approvals_required, wait_until, org_id from governance_requests"
        " where id = %s",
        [str(request_id)],
    ).fetchone()
    if (
        not req
        or str(req["org_id"]) != str(org_id)
        or req["kind"] not in {"org_delete", "workspace_destroy"}
    ):
        raise KeyGuardRefusal("no matching destruction request")
    if req["state"] != "executable":
        raise KeyGuardRefusal(f"request is {req['state']}, not executable")
    if req["wait_until"] is None or req["wait_until"] > now:
        raise KeyGuardRefusal("waiting window has not elapsed")
    rows = conn.execute(
        "select approver_id, authenticator_id, approver_kind, step_up_at from governance_approvals"
        " where request_id = %s and decision = 'approve'",
        [str(request_id)],
    ).fetchall()
    approvals = [
        Approval(
            str(r["approver_id"]),
            str(r["authenticator_id"]),
            str(r["approver_kind"]),
            r["step_up_at"],
        )
        for r in rows
    ]
    _check_distinct(
        approvals, initiator=str(req["initiator_id"]), required=int(req["approvals_required"])
    )
    if not any(a.approver_kind == "operator" for a in approvals):
        raise KeyGuardRefusal("the key stage needs an operator key_custodian approval")
    keys = conn.execute(
        "select key_ref, replica_ref, escrow_ref, deletion_protection from org_keys where org_id = %s",
        [str(org_id)],
    ).fetchall()
    refs: list[str] = []
    for k in keys:
        # Replica first: a multi-Region primary cannot finish deletion while replicas exist (second hold).
        refs += [r for r in (k["replica_ref"], k["key_ref"], k["escrow_ref"]) if r]
    return DestructionPlan(
        str(org_id), str(request_id), refs, PRODUCTION_DELETION_WINDOW_DAYS, approvals
    )


def _check_distinct(approvals: Sequence[Approval], *, initiator: str, required: int) -> None:
    people = {a.approver_id for a in approvals}
    devices = {a.authenticator_id for a in approvals}
    if initiator in people:
        raise KeyGuardRefusal("the initiator cannot approve")
    if len(people) < required or len(devices) < required or len(approvals) != len(people):
        raise KeyGuardRefusal(f"needs {required} distinct approvers with distinct authenticators")


def schedule_destruction(
    provider: KeyProvider, plan: DestructionPlan, *, drill: bool = False
) -> list[str]:
    window = (
        DRILL_DELETION_WINDOW_DAYS
        if drill
        else max(plan.window_days, PRODUCTION_DELETION_WINDOW_DAYS)
    )
    for ref in plan.key_refs:
        provider.schedule_deletion(ref, window_days=window)
    return plan.key_refs


# --- detective control: the responder -------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyEvent:
    event_name: str
    key_ref: str
    principal_arn: str
    event_time: datetime
    session_tags: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_cloudtrail(cls, detail: Mapping[str, Any]) -> KeyEvent:
        params = detail.get("requestParameters") or {}
        identity = detail.get("userIdentity") or {}
        tags = (identity.get("sessionContext") or {}).get("sessionTags") or {}
        return cls(
            event_name=str(detail.get("eventName", "")),
            key_ref=str(params.get("keyId", "")),
            principal_arn=str(identity.get("arn", "")),
            event_time=datetime.fromisoformat(
                str(detail.get("eventTime", "1970-01-01T00:00:00+00:00")).replace("Z", "+00:00")
            ),
            session_tags={str(k): str(v) for k, v in tags.items()},
        )


def is_approved(event: KeyEvent, approved_requests: Mapping[str, set[str]]) -> bool:
    """An event is approved when it came from keyguard-destroyer with session tags naming an executable request
    whose plan lists this key, and two distinct approval IDs."""
    if event.event_name in {"CancelKeyDeletion"}:
        return True  # restoring is always allowed
    if ":assumed-role/keyguard-destroyer/" not in event.principal_arn:
        return False
    request = event.session_tags.get("lmqa:request_id", "")
    first, second = (
        event.session_tags.get("lmqa:approval_1"),
        event.session_tags.get("lmqa:approval_2"),
    )
    if not first or not second or first == second:
        return False
    return event.key_ref in approved_requests.get(request, set())


def respond(
    provider: KeyProvider, event: KeyEvent, approved_requests: Mapping[str, set[str]]
) -> str:
    """Undo an unapproved destructive key event. Returns the action taken (for the page and the audit record)."""
    if event.event_name not in WATCHED_EVENTS:
        return "ignored"
    if is_approved(event, approved_requests):
        return "approved"
    if event.event_name == "ScheduleKeyDeletion":
        provider.cancel_deletion(event.key_ref)
        provider.enable(event.key_ref)
        return "cancelled_and_enabled"
    if event.event_name == "DisableKey":
        provider.enable(event.key_ref)
        return "enabled"
    return "paged"  # policy and key-material changes page security; they cannot be undone automatically


# --- preventive control lint ----------------------------------------------------------------------------------


def lint_key_policy(
    policy: Mapping[str, Any] | str, *, window_days: int | None = None, drill: bool = False
) -> list[str]:
    """Problems with a production key policy; an empty list means it passes (G1.12, G11.1)."""
    doc = json.loads(policy) if isinstance(policy, str) else dict(policy)
    problems: list[str] = []
    allowed_arn_markers = tuple(f":role/{r}" for r in ALLOWED_DESTRUCTIVE_ROLES)
    explicit_deny = False
    for stmt in doc.get("Statement", []):
        actions = stmt.get("Action", [])
        actions = [actions] if isinstance(actions, str) else list(actions)
        effect = stmt.get("Effect")
        touches = [a for a in actions if a in DESTRUCTIVE_ACTIONS or a in {"kms:*", "*"}]
        if not touches:
            continue
        principals = stmt.get("Principal", {})
        arns = principals.get("AWS", []) if isinstance(principals, dict) else principals
        arns = [arns] if isinstance(arns, str) else list(arns)
        if effect == "Allow":
            for arn in arns:
                if not arn.endswith(allowed_arn_markers) and not (
                    arn.endswith(":root") and _has_role_condition(stmt)
                ):
                    problems.append(f"{arn} may {', '.join(touches)}")
        if effect == "Deny" and ("kms:*" in actions or set(DESTRUCTIVE_ACTIONS) <= set(actions)):
            explicit_deny = True
    if not explicit_deny:
        problems.append(
            "no explicit Deny of the destructive actions for principals other than the named roles"
        )
    minimum = DRILL_DELETION_WINDOW_DAYS if drill else PRODUCTION_DELETION_WINDOW_DAYS
    if window_days is not None and window_days < minimum:
        problems.append(f"deletion window {window_days} d is below {minimum} d")
    return problems


def _has_role_condition(stmt: Mapping[str, Any]) -> bool:
    cond = json.dumps(stmt.get("Condition", {}))
    return all(role in cond for role in ALLOWED_DESTRUCTIVE_ROLES[:1])
