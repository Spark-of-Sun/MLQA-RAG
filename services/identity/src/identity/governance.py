"""Governance requests: the one mechanism for control-plane actions that need two people and a wait (blueprint 6.7,
G2.10, G9.9).

    requested -> approved -> waiting -> executable -> executed
    exits: rejected, cancelled (the initiator, at any open state), expired (approvals expire after 72 h), failed

Rules enforced here and again by database constraints:
* the initiator cannot approve; one human cannot approve twice (primary key); one authenticator cannot approve twice
  (unique), so two approvals need two distinct authenticators as well as two people;
* each approval needs passkey step-up within `Policy.step_up_max_age` (5 minutes in production);
* a veto (owner_recovery: any admin or the co-owner) rejects the request;
* the wait starts when the last required approval arrives; `tick()` moves due requests forward and expires stale
  ones; effects run only from `executable`, exactly once, in the same transaction that marks the request executed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import lmqa_audit
from lmqa_models.contracts import transition
from lmqa_models.errors import BadRequest, Conflict, Forbidden, NotFound
from lmqa_models.policy import Policy

ConnFactory = Callable[[], AbstractContextManager[Any]]
Effect = Callable[[Any, dict[str, Any]], None]


@dataclass(frozen=True)
class KindRule:
    initiators: frozenset[str]  # super_admin, admin, operator_support, ...
    approvers: frozenset[str]
    approvals_required: int
    target_type: str


RULES: Mapping[str, KindRule] = {
    "successor_transfer": KindRule(
        frozenset({"super_admin"}), frozenset({"co_owner", "security_officer"}), 1, "workspace"
    ),
    "private_read_enable": KindRule(
        frozenset({"admin"}), frozenset({"super_admin", "co_owner"}), 1, "workspace"
    ),
    "wall_lift": KindRule(
        frozenset({"admin", "super_admin"}),
        frozenset({"super_admin", "co_owner", "security_officer"}),
        1,
        "wall",
    ),
    "workspace_unseal": KindRule(
        frozenset({"super_admin", "co_owner"}),
        frozenset({"co_owner", "key_custodian"}),
        1,
        "workspace",
    ),
    "workspace_destroy": KindRule(
        frozenset({"super_admin", "co_owner"}),
        frozenset({"co_owner", "security_officer", "key_custodian"}),
        2,
        "workspace",
    ),
    "org_delete": KindRule(
        frozenset({"super_admin"}),
        frozenset({"co_owner", "security_officer", "key_custodian"}),
        2,
        "organization",
    ),
    "owner_recovery": KindRule(
        frozenset({"support"}), frozenset({"security_officer", "support"}), 2, "organization"
    ),
    "co_owner_set": KindRule(frozenset({"super_admin"}), frozenset({"invitee"}), 1, "membership"),
}


@dataclass(frozen=True)
class Actor:
    """A human acting on a governance request: a customer user or an operator, with their step-up proof."""

    id: str
    kind: str  # user | operator
    roles: frozenset[str]
    authenticator_id: str | None = None
    step_up_at: datetime | None = None


class GovernanceService:
    def __init__(
        self, conn: ConnFactory, policy: Policy, effects: Mapping[str, Effect] | None = None
    ) -> None:
        self._conn = conn
        self._policy = policy
        self._effects = dict(effects or {})

    def register(self, kind: str, effect: Effect) -> None:
        self._effects[kind] = effect

    # --- create ---------------------------------------------------------------------------------------------

    def create(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        actor: Actor,
        *,
        org_id: str,
        kind: str,
        target_id: str,
        reason_code: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        rule = RULES.get(kind)
        if rule is None:
            raise BadRequest("unknown governance request kind")
        if not actor.roles & rule.initiators:
            raise Forbidden("you cannot start this request")
        now = datetime.now(UTC)
        with self._conn() as conn:
            try:
                row = conn.execute(
                    "insert into governance_requests (org_id, workspace_id, kind, target_type, target_id,"
                    " reason_code, initiator_id, initiator_kind, approvals_required, wait_seconds, expires_at)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning *",
                    [
                        org_id,
                        workspace_id,
                        kind,
                        rule.target_type,
                        target_id,
                        reason_code,
                        actor.id,
                        actor.kind,
                        rule.approvals_required,
                        self._policy.wait_for(kind),
                        now + timedelta(seconds=self._policy.approval_expiry),
                    ],
                ).fetchone()
            except Exception as exc:
                if "governance_one_open_per_target" in str(exc):
                    raise Conflict("a request for this target is already open") from exc
                raise
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=workspace_id,
                actor_id=_user(actor),
                action="governance.requested",
                target_type="governance_request",
                target_id=row["id"],
                payload={"kind": kind, "reason": reason_code},
            )
        return dict(row)

    # --- decide ---------------------------------------------------------------------------------------------

    def approve(self, actor: Actor, request_id: str) -> dict[str, Any]:
        return self._decide(actor, request_id, "approve")

    def reject(self, actor: Actor, request_id: str) -> dict[str, Any]:
        return self._decide(actor, request_id, "reject")

    def veto(self, actor: Actor, request_id: str) -> dict[str, Any]:
        return self._decide(actor, request_id, "veto")

    def _decide(self, actor: Actor, request_id: str, decision: str) -> dict[str, Any]:  # noqa: C901, PLR0912 - one linear flow; splitting it is a DEV-33 follow-up
        now = datetime.now(UTC)
        with self._conn() as conn:
            req = conn.execute(
                "select * from governance_requests where id = %s for update", [request_id]
            ).fetchone()
            if not req:
                raise NotFound("not found")
            rule = RULES[req["kind"]]
            if str(req["initiator_id"]) == actor.id:
                raise Forbidden("the initiator cannot decide their own request")
            if decision != "veto" and not actor.roles & rule.approvers:
                raise Forbidden("you cannot decide this request")
            if decision == "veto" and req["kind"] != "owner_recovery":
                raise BadRequest("only owner recovery can be vetoed")
            if req["state"] != "requested":
                raise Conflict(f"request is {req['state']}")
            if req["expires_at"] <= now:
                self._move(conn, req, "expire")
                raise Conflict("request expired")
            if decision == "approve":
                if not actor.authenticator_id or not actor.step_up_at:
                    raise Forbidden("step_up_required")
                if (now - actor.step_up_at).total_seconds() > self._policy.step_up_max_age:
                    raise Forbidden("step_up_required")
            try:
                conn.execute(
                    "insert into governance_approvals (request_id, approver_id, approver_kind, authenticator_id,"
                    " step_up_at, decision) values (%s, %s, %s, %s, %s, %s)",
                    [
                        request_id,
                        actor.id,
                        actor.kind,
                        actor.authenticator_id or f"none:{actor.id}",
                        actor.step_up_at or now,
                        decision,
                    ],
                )
            except Exception as exc:
                raise Conflict("this person or authenticator has already decided") from exc
            if decision in {"reject", "veto"}:
                req = self._move(conn, req, "reject")
            else:
                count = conn.execute(
                    "select count(distinct approver_id) as n from governance_approvals"
                    " where request_id = %s and decision = 'approve'",
                    [request_id],
                ).fetchone()["n"]
                if count >= req["approvals_required"]:
                    req = self._move(conn, req, "approve")
                    req = self._move(
                        conn,
                        req,
                        "start_wait",
                        wait_until=now + timedelta(seconds=int(req["wait_seconds"])),
                    )
            lmqa_audit.append(
                conn,
                org_id=req["org_id"],
                workspace_id=req["workspace_id"],
                actor_id=_user(actor),
                action=f"governance.{decision}",
                target_type="governance_request",
                target_id=request_id,
                payload={"kind": req["kind"], "actor_kind": actor.kind},
            )
        return dict(req)

    def cancel(self, actor: Actor, request_id: str) -> dict[str, Any]:
        """The initiator can always cancel an open request (restoring direction)."""
        with self._conn() as conn:
            req = conn.execute(
                "select * from governance_requests where id = %s for update", [request_id]
            ).fetchone()
            if not req:
                raise NotFound("not found")
            if str(req["initiator_id"]) != actor.id:
                raise Forbidden("only the initiator can cancel")
            action = {
                "requested": "cancel",
                "approved": "cancel_approved",
                "waiting": "cancel_waiting",
                "executable": "cancel_executable",
            }.get(req["state"])
            if not action:
                raise Conflict(f"request is {req['state']}")
            req = self._move(conn, req, action)
            lmqa_audit.append(
                conn,
                org_id=req["org_id"],
                workspace_id=req["workspace_id"],
                actor_id=_user(actor),
                action="governance.cancelled",
                target_type="governance_request",
                target_id=request_id,
                payload={"kind": req["kind"]},
            )
        return dict(req)

    # --- time and execution ---------------------------------------------------------------------------------

    def tick(self) -> dict[str, int]:
        """Expire stale requests, open waits that are over, and execute what is executable. Run every minute."""
        now = datetime.now(UTC)
        counts = {"expired": 0, "executable": 0, "executed": 0, "failed": 0}
        with self._conn() as conn:
            for req in conn.execute(
                "select * from governance_requests where state = 'requested' and expires_at <= %s for update"
                " skip locked",
                [now],
            ).fetchall():
                self._move(conn, req, "expire")
                counts["expired"] += 1
            for req in conn.execute(
                "select * from governance_requests where state = 'waiting' and wait_until <= %s for update skip locked",
                [now],
            ).fetchall():
                self._move(conn, req, "wait_over")
                counts["executable"] += 1
        with self._conn() as conn:
            due = conn.execute(
                "select id from governance_requests where state = 'executable' order by created_at"
            ).fetchall()
        for row in due:
            counts["executed" if self.execute(str(row["id"])) else "failed"] += 1
        return counts

    def execute(self, request_id: str) -> bool:
        with self._conn() as conn:
            req = conn.execute(
                "select * from governance_requests where id = %s and state = 'executable' for update skip locked",
                [request_id],
            ).fetchone()
            if not req:
                return False
            effect = self._effects.get(req["kind"])
            if effect is None:
                self._move(conn, req, "fail", failure="no effect registered")
                return False
            try:
                with conn.transaction():
                    effect(conn, dict(req))
            except Exception as exc:
                self._move(conn, req, "fail", failure=type(exc).__name__ + ": " + str(exc)[:300])
                lmqa_audit.append(
                    conn,
                    org_id=req["org_id"],
                    workspace_id=req["workspace_id"],
                    action="governance.failed",
                    target_type="governance_request",
                    target_id=request_id,
                    payload={"kind": req["kind"]},
                )
                return False
            self._move(conn, req, "execute", executed_at=datetime.now(UTC))
            lmqa_audit.append(
                conn,
                org_id=req["org_id"],
                workspace_id=req["workspace_id"],
                action="governance.executed",
                target_type="governance_request",
                target_id=request_id,
                payload={"kind": req["kind"]},
            )
        return True

    # --- reads ----------------------------------------------------------------------------------------------

    def list_for_org(self, org_id: str, *, opaque: bool = True) -> list[dict[str, Any]]:
        """Approvers see opaque IDs and reason codes only (5.6: the existence of a wall is itself sensitive)."""
        with self._conn() as conn:
            rows = conn.execute(
                "select id, kind, state, reason_code, target_type, target_id, created_at, wait_until, expires_at,"
                " approvals_required, (select count(*) from governance_approvals a where a.request_id = r.id"
                " and a.decision = 'approve') as approvals from governance_requests r where org_id = %s"
                " order by created_at desc limit 200",
                [org_id],
            ).fetchall()
        out = [dict(r) for r in rows]
        if opaque:
            for r in out:
                r["target_id"] = str(r["target_id"])[:8] + "…"
        return out

    # --- internals ------------------------------------------------------------------------------------------

    @staticmethod
    def _move(conn: Any, req: Mapping[str, Any], action: str, **extra: Any) -> dict[str, Any]:
        t = transition("governance_request", action)
        if t is None or t.from_status != req["state"]:
            raise Conflict(f"illegal governance transition {req['state']} --{action}->")
        sets = ["state = %s", "updated_at = now()"] + [f"{k} = %s" for k in extra]
        row = conn.execute(
            f"update governance_requests set {', '.join(sets)} where id = %s returning *",  # noqa: S608 - column names are keyword args from this module; values bound
            [t.to_status, *extra.values(), req["id"]],
        ).fetchone()
        return dict(row)


def _user(actor: Actor) -> str | None:
    return actor.id if actor.kind == "user" else None
