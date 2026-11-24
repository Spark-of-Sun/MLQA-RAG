"""Matters, grants, walls, emergency access and break-glass sessions (blueprint 5.4 to 5.8, G5.5 to G5.7, G9.8).

All changes go through the control plane (identity); every one bumps the affected user's `scope_version` and
`scope_hash` (database triggers in 11_access.sql) and is audited. Asymmetries from the blueprint:

* creating a wall is one admin, instant; lifting one is a `wall_lift` governance request (governance.py);
* an emergency exception is self-service for a tenant in an opted-in medical workspace, 60 minutes, tier cap 3,
  at most 5 per user per day, admin notified at once, review task due in 72 hours;
* a break-glass session needs `admin_can_read_private` (itself a governance request), a reason and passkey
  step-up within 5 minutes; at most 60 minutes; visible to affected tenants in their audit history.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import lmqa_audit
from lmqa_models.errors import BadRequest, Conflict, Forbidden, NotFound, TooManyRequests
from lmqa_models.policy import Policy
from lmqa_models.principal import Principal

ConnFactory = Callable[[], AbstractContextManager[Any]]
Notify = Callable[[Any, str, str, dict[str, Any]], None]  # (conn, user_id, kind, vars)

WALL_REASONS = {
    "conflict_of_interest",
    "lateral_hire",
    "client_instruction",
    "personal_relationship",
    "other",
}
EMERGENCY_REASONS = {"treatment_emergency", "urgent_care_continuity", "other"}


def _require_admin(p: Principal) -> tuple[str, str]:
    m = p.membership
    if not m or m.role != "admin" or not m.active or not m.workspace_id:
        raise NotFound("not found")
    return m.org_id, m.workspace_id


def _require_tenant(p: Principal) -> tuple[str, str]:
    m = p.membership
    if not m or m.role != "tenant" or not m.active or not m.workspace_id:
        raise NotFound("not found")
    return m.org_id, m.workspace_id


class ScopeAdmin:
    def __init__(self, conn: ConnFactory, policy: Policy, notify: Notify | None = None) -> None:
        self._conn = conn
        self._policy = policy
        self._notify = notify or (lambda *_: None)

    # --- matters and grants ---------------------------------------------------------------------------------

    def create_matter(self, p: Principal, label: str, kind: str) -> dict[str, Any]:
        org_id, ws = _require_admin(p)
        if kind not in {"matter", "patient"} or not 1 <= len(label.strip()) <= 200:
            raise BadRequest("invalid matter")
        with self._conn() as conn:
            row = conn.execute(
                "insert into matters (org_id, workspace_id, label, kind, created_by) values (%s, %s, %s, %s, %s)"
                " returning id, label, kind, created_at",
                [org_id, ws, label.strip(), kind, p.user_id],
            ).fetchone()
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="matter.created",
                target_type="matter",
                target_id=row["id"],
                payload={"kind": kind},
            )
        return dict(row)

    def list_matters(self, p: Principal) -> list[dict[str, Any]]:
        org_id, ws = _require_admin(p)
        del org_id
        with self._conn() as conn:
            rows = conn.execute(
                "select m.id, m.label, m.kind, m.created_at, m.closed_at,"
                " (select count(*) from matter_grants g where g.matter_id = m.id) as grants,"
                " (select count(*) from matter_walls w where w.matter_id = m.id and w.lifted_at is null) as walls"
                " from matters m where m.workspace_id = %s order by m.created_at desc",
                [ws],
            ).fetchall()
        return [dict(r) for r in rows]

    def _member_of(self, conn: Any, ws: str, user_id: str) -> dict[str, Any]:
        row = conn.execute(
            "select user_id, role, status from memberships where workspace_id = %s and user_id = %s"
            " and status not in ('rejected', 'removed')",
            [ws, user_id],
        ).fetchone()
        if not row:
            raise NotFound("not found")
        return dict(row)

    def _matter(self, conn: Any, ws: str, matter_id: str) -> dict[str, Any]:
        row = conn.execute(
            "select id, org_id, kind from matters where id = %s and workspace_id = %s",
            [matter_id, ws],
        ).fetchone()
        if not row:
            raise NotFound("not found")
        return dict(row)

    def grant(
        self,
        p: Principal,
        matter_id: str,
        user_id: str,
        max_tier: int,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        org_id, ws = _require_admin(p)
        if not 1 <= max_tier <= 4:
            raise BadRequest("max_tier must be 1 to 4")
        with self._conn() as conn:
            self._matter(conn, ws, matter_id)
            if self._member_of(conn, ws, user_id)["role"] != "tenant":
                raise BadRequest("grants are for members")
            row = conn.execute(
                "insert into matter_grants (org_id, workspace_id, matter_id, user_id, max_tier, granted_by, expires_at)"
                " values (%s, %s, %s, %s, %s, %s, %s)"
                " on conflict (matter_id, user_id) do update set max_tier = excluded.max_tier,"
                " expires_at = excluded.expires_at, granted_by = excluded.granted_by, granted_at = now()"
                " returning id, max_tier, expires_at",
                [org_id, ws, matter_id, user_id, max_tier, p.user_id, expires_at],
            ).fetchone()
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="grant.set",
                target_type="matter",
                target_id=matter_id,
                payload={"user": user_id, "max_tier": max_tier},
            )
        return dict(row)

    def revoke_grant(self, p: Principal, matter_id: str, user_id: str) -> None:
        org_id, ws = _require_admin(p)
        with self._conn() as conn:
            done = conn.execute(
                "delete from matter_grants where matter_id = %s and user_id = %s and workspace_id = %s",
                [matter_id, user_id, ws],
            ).rowcount
            if not done:
                raise NotFound("not found")
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="grant.revoked",
                target_type="matter",
                target_id=matter_id,
                payload={"user": user_id},
            )

    # --- walls ----------------------------------------------------------------------------------------------

    def create_wall(
        self, p: Principal, matter_id: str, user_id: str, reason_code: str
    ) -> dict[str, Any]:
        """One admin, instant (5.6). The walled user is told only 'no access'."""
        org_id, ws = _require_admin(p)
        if reason_code not in WALL_REASONS:
            raise BadRequest("invalid reason")
        if user_id == p.user_id:
            raise BadRequest("an admin cannot wall themselves")
        with self._conn() as conn:
            self._matter(conn, ws, matter_id)
            self._member_of(conn, ws, user_id)
            try:
                row = conn.execute(
                    "insert into matter_walls (org_id, workspace_id, matter_id, user_id, reason_code, created_by)"
                    " values (%s, %s, %s, %s, %s, %s) returning id, effective_from",
                    [org_id, ws, matter_id, user_id, reason_code, p.user_id],
                ).fetchone()
            except Exception as exc:
                raise Conflict("a wall already exists") from exc
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="wall.created",
                target_type="wall",
                target_id=row["id"],
                payload={"reason": reason_code},
            )
        return dict(row)

    def wall_on_admin(
        self, super_admin: Principal, workspace_id: str, matter_id: str, reason_code: str
    ) -> dict[str, Any]:
        """Only the Super Admin walls an admin (5.6); lifting it needs an operator security officer."""
        m = super_admin.membership
        if not m or m.role != "super_admin" or not m.active:
            raise NotFound("not found")
        with self._conn() as conn:
            ws = conn.execute(
                "select org_id, admin_user_id from workspaces where id = %s and org_id = %s",
                [workspace_id, m.org_id],
            ).fetchone()
            if not ws or not ws["admin_user_id"]:
                raise NotFound("not found")
            self._matter(conn, workspace_id, matter_id)
            row = conn.execute(
                "insert into matter_walls (org_id, workspace_id, matter_id, user_id, reason_code, created_by)"
                " values (%s, %s, %s, %s, %s, %s) returning id",
                [
                    m.org_id,
                    workspace_id,
                    matter_id,
                    ws["admin_user_id"],
                    reason_code,
                    super_admin.user_id,
                ],
            ).fetchone()
            lmqa_audit.append(
                conn,
                org_id=m.org_id,
                workspace_id=workspace_id,
                actor_id=super_admin.user_id,
                action="wall.created",
                target_type="wall",
                target_id=row["id"],
                payload={"reason": reason_code, "on": "admin"},
            )
        return dict(row)

    @staticmethod
    def lift_wall_effect(conn: Any, request: dict[str, Any]) -> None:
        """Governance effect for `wall_lift` (runs only from `executable`)."""
        row = conn.execute(
            "update matter_walls set lifted_at = now(), lifted_by_request = %s where id = %s and lifted_at is null"
            " returning user_id, workspace_id",
            [request["id"], request["target_id"]],
        ).fetchone()
        if not row:
            raise NotFound("wall not found or already lifted")

    # --- emergency access (5.7) -----------------------------------------------------------------------------

    def request_emergency(
        self, p: Principal, matter_id: str, reason_code: str, note: str
    ) -> dict[str, Any]:
        org_id, ws = _require_tenant(p)
        if reason_code not in EMERGENCY_REASONS:
            raise BadRequest("invalid reason")
        now = datetime.now(UTC)
        with self._conn() as conn:
            wsrow = conn.execute(
                "select w.emergency_access, o.kind, w.admin_user_id from workspaces w join organizations o"
                " on o.id = w.org_id where w.id = %s",
                [ws],
            ).fetchone()
            if (
                not wsrow
                or not wsrow["emergency_access"]
                or wsrow["kind"] not in {"medical", "both"}
            ):
                raise NotFound("not found")
            self._matter(conn, ws, matter_id)
            used = conn.execute(
                "select count(*) as n from access_exceptions where user_id = %s and created_at > %s",
                [p.user_id, now - timedelta(days=1)],
            ).fetchone()["n"]
            if used >= self._policy.emergency_daily_limit:
                raise TooManyRequests("emergency access limit reached for today")
            row = conn.execute(
                "insert into access_exceptions (org_id, workspace_id, matter_id, user_id, reason_code, note,"
                " expires_at, review_due_at) values (%s, %s, %s, %s, %s, %s, %s, %s)"
                " returning id, expires_at, tier_cap",
                [
                    org_id,
                    ws,
                    matter_id,
                    p.user_id,
                    reason_code,
                    note[:2000],
                    now + timedelta(seconds=self._policy.emergency_duration),
                    now + timedelta(seconds=self._policy.review_due),
                ],
            ).fetchone()
            conn.execute(
                "insert into review_tasks (org_id, workspace_id, kind, subject_id, assignee_id, due_at)"
                " values (%s, %s, 'emergency_access', %s, %s, %s)",
                [
                    org_id,
                    ws,
                    row["id"],
                    wsrow["admin_user_id"],
                    now + timedelta(seconds=self._policy.review_due),
                ],
            )
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="emergency.started",
                target_type="access_exception",
                target_id=row["id"],
                payload={"reason": reason_code, "matter": matter_id},
            )
            if wsrow["admin_user_id"]:
                self._notify(
                    conn,
                    str(wsrow["admin_user_id"]),
                    "emergency_access_started",
                    {"exception": str(row["id"])},
                )
        return dict(row)

    def end_exception(self, p: Principal, exception_id: str) -> None:
        org_id, ws = _require_admin(p)
        with self._conn() as conn:
            done = conn.execute(
                "update access_exceptions set state = 'revoked', revoked_at = now()"
                " where id = %s and workspace_id = %s and state = 'active'",
                [exception_id, ws],
            ).rowcount
            if not done:
                raise NotFound("not found")
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="emergency.ended",
                target_type="access_exception",
                target_id=exception_id,
                payload={},
            )

    def close_review(self, p: Principal, task_id: str, outcome: str) -> None:
        org_id, ws = _require_admin(p)
        with self._conn() as conn:
            task = conn.execute(
                "update review_tasks set state = 'closed', outcome = %s, closed_by = %s, closed_at = now()"
                " where id = %s and workspace_id = %s and state = 'open' returning kind, subject_id",
                [outcome[:2000], p.user_id, task_id, ws],
            ).fetchone()
            if not task:
                raise NotFound("not found")
            if task["kind"] == "emergency_access":
                conn.execute(
                    "update access_exceptions set review_state = 'closed', reviewed_by = %s, reviewed_at = now(),"
                    " state = case when state in ('expired', 'revoked') then 'reviewed' else state end"
                    " where id = %s",
                    [p.user_id, task["subject_id"]],
                )
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="review.closed",
                target_type="review_task",
                target_id=task_id,
                payload={"kind": task["kind"]},
            )

    def list_reviews(self, p: Principal) -> list[dict[str, Any]]:
        _, ws = _require_admin(p)
        with self._conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "select id, kind, subject_id, state, due_at, created_at from review_tasks where workspace_id = %s"
                    " order by state, due_at",
                    [ws],
                ).fetchall()
            ]

    # --- break-glass (5.8) ----------------------------------------------------------------------------------

    def start_break_glass(
        self, p: Principal, reason: str, step_up_at: datetime | None
    ) -> dict[str, Any]:
        org_id, ws = _require_admin(p)
        now = datetime.now(UTC)
        if step_up_at is None or (now - step_up_at).total_seconds() > self._policy.step_up_max_age:
            raise Forbidden("step_up_required")
        if len(reason.strip()) < 10:
            raise BadRequest("state the reason (at least 10 characters)")
        with self._conn() as conn:
            flag = conn.execute(
                "select admin_can_read_private from workspaces where id = %s", [ws]
            ).fetchone()
            if not flag or not flag["admin_can_read_private"]:
                raise Forbidden("private reading is not enabled for this workspace")
            row = conn.execute(
                "insert into break_glass_sessions (org_id, workspace_id, admin_user_id, reason, step_up_at, expires_at)"
                " values (%s, %s, %s, %s, %s, %s) returning id, expires_at",
                [
                    org_id,
                    ws,
                    p.user_id,
                    reason.strip(),
                    step_up_at,
                    now + timedelta(seconds=self._policy.break_glass_duration),
                ],
            ).fetchone()
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="break_glass.started",
                target_type="break_glass_session",
                target_id=row["id"],
                payload={},  # the typed reason is free text: kept in break_glass_sessions only (R-60.5),
            )
        return dict(row)

    def end_break_glass(self, p: Principal, session_id: str) -> None:
        org_id, ws = _require_admin(p)
        with self._conn() as conn:
            done = conn.execute(
                "update break_glass_sessions set state = 'revoked', revoked_at = now()"
                " where id = %s and admin_user_id = %s and state = 'active'",
                [session_id, p.user_id],
            ).rowcount
            if not done:
                raise NotFound("not found")
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=ws,
                actor_id=p.user_id,
                action="break_glass.ended",
                target_type="break_glass_session",
                target_id=session_id,
                payload={},
            )

    @staticmethod
    def private_read_enable_effect(conn: Any, request: dict[str, Any]) -> None:
        conn.execute(
            "update workspaces set admin_can_read_private = true where id = %s",
            [request["target_id"]],
        )
        conn.execute(
            "insert into notifications (org_id, to_user_id, kind, template_vars)"
            " select %s, m.user_id, 'private_read_enabled', '{}'::jsonb from memberships m"
            " where m.workspace_id = %s and m.role = 'tenant' and m.status = 'active'",
            [request["org_id"], request["target_id"]],
        )

    # --- expiry sweeps (run every minute by the identity worker) --------------------------------------------

    def sweep(self) -> dict[str, int]:
        now = datetime.now(UTC)
        with self._conn() as conn:
            exc = conn.execute(
                "update access_exceptions set state = 'expired' where state = 'active' and expires_at <= %s",
                [now],
            ).rowcount
            bg = conn.execute(
                "update break_glass_sessions set state = 'expired' where state = 'active' and expires_at <= %s",
                [now],
            ).rowcount
            a48 = conn.execute(
                "update review_tasks set alerted_48h = true where state = 'open' and not alerted_48h"
                " and created_at <= %s returning org_id, workspace_id, id",
                [now - timedelta(hours=48)],
            ).fetchall()
            a72 = conn.execute(
                "update review_tasks set alerted_72h = true where state = 'open' and not alerted_72h"
                " and due_at <= %s returning org_id, workspace_id, id",
                [now],
            ).fetchall()
            for row, rule in [
                *((r, "review_overdue_48h") for r in a48),
                *((r, "review_overdue_72h") for r in a72),
            ]:
                conn.execute(
                    "insert into alerts (org_id, workspace_id, rule, severity, summary, dedup_key)"
                    " values (%s, %s, %s, 'warning', %s, %s) on conflict do nothing",
                    [
                        row["org_id"],
                        row["workspace_id"],
                        rule,
                        f"review task {row['id']} is overdue",
                        f"{rule}:{row['id']}",
                    ],
                )
        return {"exceptions_expired": exc, "break_glass_expired": bg, "alerts": len(a48) + len(a72)}
