"""Just-in-time operator access (blueprint 14.3, 14.4, G9.7).

* Operators hold no standing credentials. A grant is requested with a reason and a ticket, approved by a different
  operator (infrastructure) or by the customer (control plane: the Super Admin; content: the workspace admin), and
  expires on its own: 24 h infrastructure, 8 h control plane, 4 h content at most (Appendix C).
* An operator can never approve their own request (database CHECK and here).
* Every grant step is written to the customer organization's audit chain, so the customer sees it (13.5).
* `ops_metadata_ro`, the only database role an infrastructure session gets, has no policy on content tables.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import lmqa_audit
from lmqa_models.errors import BadRequest, Conflict, Forbidden, NotFound
from lmqa_models.policy import Policy

ConnFactory = Callable[[], AbstractContextManager[Any]]
PLANES = ("infrastructure", "control", "content")


@dataclass(frozen=True)
class Operator:
    id: str
    roles: frozenset[str]  # sre, support, security_officer, key_custodian, operator_admin


class JitAccess:
    def __init__(self, conn: ConnFactory, policy: Policy) -> None:
        self._conn = conn
        self._policy = policy

    def _max(self, plane: str) -> int:
        return {
            "infrastructure": self._policy.operator_infrastructure_max,
            "control": self._policy.operator_control_max,
            "content": self._policy.operator_content_max,
        }[plane]

    def request(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        op: Operator,
        *,
        org_id: str,
        plane: str,
        reason: str,
        ticket: str,
        workspace_id: str | None = None,
        hours: float = 1.0,
    ) -> dict[str, Any]:
        if plane not in PLANES:
            raise BadRequest("unknown plane")
        if plane == "infrastructure" and not op.roles & {"sre", "security_officer"}:
            raise Forbidden("infrastructure access is for SRE")
        if plane in {"control", "content"} and "support" not in op.roles:
            raise Forbidden("customer-plane access is for support")
        seconds = min(int(hours * 3600), self._max(plane))
        with self._conn() as conn:
            row = conn.execute(
                "insert into ops.operator_access_grants (operator_id, org_id, workspace_id, plane, reason, ticket_ref,"
                " expires_at) values (%s, %s, %s, %s, %s, %s, now() + make_interval(secs => %s)) returning *",
                [op.id, org_id, workspace_id, plane, reason, ticket, seconds],
            ).fetchone()
            lmqa_audit.append(
                conn,
                org_id=org_id,
                workspace_id=workspace_id,
                action="operator.access_requested",
                target_type="operator_grant",
                target_id=row["id"],
                payload={"plane": plane, "ticket": ticket},
            )
        return dict(row)

    def approve_as_operator(self, approver: Operator, grant_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            g = self._grant(conn, grant_id)
            if g["plane"] != "infrastructure":
                raise Forbidden("customer-plane access is approved by the customer")
            if str(g["operator_id"]) == approver.id:
                raise Forbidden("an operator cannot approve their own access")
            if not approver.roles & {"security_officer", "sre"}:
                raise Forbidden("needs security_officer or sre")
            return self._activate(conn, g, approved_by=approver.id)

    def approve_as_customer(
        self,
        grant_id: str,
        *,
        customer_user_id: str,
        customer_role: str,
        customer_workspace_id: str | None,
    ) -> dict[str, Any]:
        with self._conn() as conn:
            g = self._grant(conn, grant_id)
            if g["plane"] == "control" and customer_role != "super_admin":
                raise Forbidden("control-plane access is approved by the Super Admin")
            if g["plane"] == "content" and (
                customer_role != "admin" or str(g["workspace_id"]) != str(customer_workspace_id)
            ):
                raise Forbidden("content access is approved by the workspace admin")
            if g["plane"] == "infrastructure":
                raise Forbidden("infrastructure access is approved by an operator")
            return self._activate(conn, g, customer_approved_by=customer_user_id)

    def revoke(self, grant_id: str, actor: str) -> None:
        with self._conn() as conn:
            g = self._grant(conn, grant_id)
            if g["state"] != "active":
                raise Conflict(f"grant is {g['state']}")
            conn.execute(
                "update ops.operator_access_grants set state = 'revoked', revoked_at = now() where id = %s",
                [grant_id],
            )
            lmqa_audit.append(
                conn,
                org_id=g["org_id"],
                workspace_id=g["workspace_id"],
                action="operator.access_revoked",
                target_type="operator_grant",
                target_id=grant_id,
                payload={"by": actor},
            )

    def expire_due(self) -> int:
        with self._conn() as conn:
            rows = conn.execute(
                "update ops.operator_access_grants set state = 'expired' where state = 'active' and expires_at <= now()"
                " returning id, org_id, workspace_id"
            ).fetchall()
            for r in rows:
                lmqa_audit.append(
                    conn,
                    org_id=r["org_id"],
                    workspace_id=r["workspace_id"],
                    action="operator.access_expired",
                    target_type="operator_grant",
                    target_id=r["id"],
                    payload={},
                )
        return len(rows)

    def active_grant(self, operator_id: str, org_id: str, plane: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "select * from ops.operator_access_grants where operator_id = %s and org_id = %s and plane = %s"
                " and state = 'active' and expires_at > now() order by expires_at desc limit 1",
                [operator_id, org_id, plane],
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _grant(conn: Any, grant_id: str) -> dict[str, Any]:
        g = conn.execute(
            "select * from ops.operator_access_grants where id = %s for update", [grant_id]
        ).fetchone()
        if not g:
            raise NotFound("not found")
        return dict(g)

    def _activate(self, conn: Any, g: dict[str, Any], **who: str) -> dict[str, Any]:
        if g["state"] != "requested":
            raise Conflict(f"grant is {g['state']}")
        now = datetime.now(UTC)
        expires = min(g["expires_at"], now + timedelta(seconds=self._max(g["plane"])))
        sets = ", ".join(f"{k} = %s" for k in who)
        row = conn.execute(
            f"update ops.operator_access_grants set state = 'active', starts_at = now(), expires_at = %s, {sets}"  # noqa: S608 - column names are keyword args from this module; values bound
            " where id = %s returning *",
            [expires, *who.values(), g["id"]],
        ).fetchone()
        lmqa_audit.append(
            conn,
            org_id=g["org_id"],
            workspace_id=g["workspace_id"],
            action="operator.access_granted",
            target_type="operator_grant",
            target_id=g["id"],
            payload={"plane": g["plane"], "expires_at": expires.isoformat()},
        )
        return dict(row)
