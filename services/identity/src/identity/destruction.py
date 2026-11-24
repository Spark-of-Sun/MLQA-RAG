"""Organization and workspace destruction, sealing and retention (blueprint 6.3, 6.4, 7.8, 9.5, 12.6, 12.7, G9.5,
G9.6).

The ritual for an organization (12.7), at least 60 days from request to irreversible destruction:

  R1 org_delete governance request approved -> `deletion_pending` (effect below); workspaces frozen; notices
  R2 30-day grace: export window; one person can cancel (cancel_delete)
  R4 `sealed`: workspace content keys sealed (CMK copies removed, escrow kept); KeyGuard schedules the CMK, the
     replica (first) and the escrow key with the 30-day provider window after a custodian approves the key stage
  R6 provider window over: keys gone; vectors, objects and the Auth0 Organization deleted; `destroyed`
  R7 destruction record and tombstone

Restoring is easy at every step before R6: cancel the deletion, re-enable the key, release (one person plus a
custodian). Retention and legal hold are checked at every step; a hold stops the clock.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any

import lmqa_audit
from identity.lifecycle import freeze_workspace_cascade
from lmqa_keys.keyguard import KeyGuardRefusal, authorize_destruction, schedule_destruction
from lmqa_keys.keyring import KeyRing
from lmqa_keys.providers import KeyProvider
from lmqa_models.policy import Policy

ConnFactory = Callable[[], AbstractContextManager[Any]]


def org_delete_effect(conn: Any, request: dict[str, Any]) -> None:
    """R1: the request was approved and its wait is over."""
    org = request["target_id"]
    held = conn.execute("select legal_hold from organizations where id = %s", [org]).fetchone()
    if held and held["legal_hold"]:
        raise KeyGuardRefusal("organization is under legal hold")
    conn.execute(
        "update organizations set status = 'deletion_pending', deletion_requested_at = now(),"
        " state_changed_at = now() where id = %s and status in ('active', 'frozen')",
        [org],
    )
    for ws in conn.execute(
        "select id from workspaces where org_id = %s and status = 'active'", [org]
    ).fetchall():
        freeze_workspace_cascade(conn, str(ws["id"]), reason="org_frozen")
    conn.execute(
        "insert into notifications (org_id, to_user_id, kind, template_vars) select %s, m.user_id, 'suspended',"
        " '{}'::jsonb from memberships m where m.org_id = %s and m.role in ('admin', 'super_admin')",
        [org, org],
    )
    lmqa_audit.append(
        conn,
        org_id=org,
        action="org.deletion_pending",
        target_type="organization",
        target_id=org,
        payload={"request": str(request["id"])},
    )


def workspace_destroy_effect_factory(keyring: KeyRing) -> Callable[[Any, dict[str, Any]], None]:
    def effect(conn: Any, request: dict[str, Any]) -> None:
        ws = request["target_id"]
        row = conn.execute(
            "select w.status, w.legal_hold, o.legal_hold as org_hold, w.org_id from workspaces w"
            " join organizations o on o.id = w.org_id where w.id = %s",
            [ws],
        ).fetchone()
        if not row or row["status"] != "sealed":
            raise KeyGuardRefusal("workspace must be sealed")
        if row["legal_hold"] or row["org_hold"]:
            raise KeyGuardRefusal("legal hold")
        open_retention = conn.execute(
            "select 1 from documents where workspace_id = %s and retention_until > now() limit 1",
            [ws],
        ).fetchone()
        if open_retention:
            raise KeyGuardRefusal("retention has not ended")
        conn.execute(
            "update workspace_keys set wrapped_key = '\\x00'::bytea, escrow_wrapped = null,"
            " state = 'destroyed' where workspace_id = %s",
            [ws],
        )
        conn.execute(
            "update workspaces set status = 'destroyed', state_changed_at = now() where id = %s",
            [ws],
        )
        conn.execute(
            "insert into deletion_tombstones (org_id, workspace_id, scope, target_id) values (%s, %s, 'workspace', %s)",
            [row["org_id"], ws, ws],
        )
        keyring.forget(ws)
        lmqa_audit.append(
            conn,
            org_id=row["org_id"],
            workspace_id=ws,
            action="workspace.destroyed",
            target_type="workspace",
            target_id=ws,
            payload={"request": str(request["id"])},
        )

    return effect


def workspace_unseal_effect_factory(keyring: KeyRing, escrow: tuple[KeyProvider, str] | None):
    def effect(conn: Any, request: dict[str, Any]) -> None:
        if escrow is None:
            raise KeyGuardRefusal("escrow is not configured")
        ws = request["target_id"]
        org = conn.execute(
            "select org_id from workspaces where id = %s and status = 'sealed'", [ws]
        ).fetchone()
        if not org:
            raise KeyGuardRefusal("workspace is not sealed")
        keyring.unseal_workspace(conn, org["org_id"], ws, escrow)
        conn.execute(
            "update workspaces set status = 'frozen', sealed_at = null, state_changed_at = now() where id = %s",
            [ws],
        )
        lmqa_audit.append(
            conn,
            org_id=org["org_id"],
            workspace_id=ws,
            action="workspace.unsealed",
            target_type="workspace",
            target_id=ws,
            payload={"request": str(request["id"])},
        )

    return effect


class Lifecycle:
    """The clock: sealing after inactivity windows, the deletion grace, and retention (run every few minutes)."""

    def __init__(
        self, conn: ConnFactory, policy: Policy, keyring: KeyRing, provider: KeyProvider
    ) -> None:
        self._conn = conn
        self._policy = policy
        self._keyring = keyring
        self._provider = provider

    def tick(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(UTC)
        out = {"sealed_workspaces": 0, "sealed_orgs": 0, "retention_due": 0}
        with self._conn() as conn:
            # 7.8: a frozen workspace with no successor for 30 days is sealed.
            for ws in conn.execute(
                "select id, org_id from workspaces where status = 'frozen' and not legal_hold and frozen_at < %s",
                [now - timedelta(seconds=self._policy.workspace_seal_after)],
            ).fetchall():
                self._keyring.seal_workspace(conn, ws["id"])
                conn.execute(
                    "update workspaces set status = 'sealed', sealed_at = now(), state_changed_at = now()"
                    " where id = %s",
                    [ws["id"]],
                )
                lmqa_audit.append(
                    conn,
                    org_id=ws["org_id"],
                    workspace_id=ws["id"],
                    action="workspace.sealed",
                    target_type="workspace",
                    target_id=ws["id"],
                    payload={"reason": "no_successor"},
                )
                out["sealed_workspaces"] += 1
            # R2 -> R4: deletion grace over.
            for org in conn.execute(
                "select id from organizations where status = 'deletion_pending' and not legal_hold"
                " and deletion_requested_at < %s",
                [now - timedelta(seconds=self._policy.org_delete_grace)],
            ).fetchall():
                for ws in conn.execute(
                    "select id from workspaces where org_id = %s and status in ('frozen', 'active')",
                    [org["id"]],
                ).fetchall():
                    self._keyring.seal_workspace(conn, ws["id"])
                    conn.execute(
                        "update workspaces set status = 'sealed', sealed_at = now() where id = %s",
                        [ws["id"]],
                    )
                conn.execute(
                    "update organizations set status = 'sealed', state_changed_at = now() where id = %s",
                    [org["id"]],
                )
                lmqa_audit.append(
                    conn,
                    org_id=org["id"],
                    action="org.sealed",
                    target_type="organization",
                    target_id=org["id"],
                    payload={},
                )
                out["sealed_orgs"] += 1
            out["retention_due"] = conn.execute(
                "select count(*) as n from documents where retention_until < %s and not legal_hold"
                " and lifecycle not in ('deleting', 'deleted')",
                [now],
            ).fetchone()["n"]
        return out

    def schedule_key_stage(self, org_id: str, request_id: str, *, drill: bool = False) -> list[str]:
        """R4 key stage: KeyGuard checks every condition, then schedules with the policy window."""
        with self._conn() as conn:
            plan = authorize_destruction(conn, org_id, request_id)
            refs = schedule_destruction(self._provider, plan, drill=drill)
            conn.execute(
                "update org_keys set state = 'pending_deletion' where org_id = %s", [org_id]
            )
            lmqa_audit.append(
                conn,
                org_id=org_id,
                action="org.keys_scheduled",
                target_type="organization",
                target_id=org_id,
                payload={"keys": len(refs), "window_days": plan.window_days},
            )
        return refs

    def restore(self, org_id: str, actor_id: str) -> None:
        """Easy direction (12.5): cancel scheduled deletion, re-enable keys, back to `frozen`."""
        with self._conn() as conn:
            keys = conn.execute(
                "select key_ref, replica_ref, escrow_ref from org_keys where org_id = %s", [org_id]
            ).fetchall()
            for k in keys:
                for ref in (k["key_ref"], k["replica_ref"], k["escrow_ref"]):
                    if ref:
                        self._provider.cancel_deletion(ref)
                        self._provider.enable(ref)
            conn.execute("update org_keys set state = 'enabled' where org_id = %s", [org_id])
            conn.execute(
                "update organizations set status = 'frozen', state_changed_at = now() where id = %s"
                " and status = 'sealed'",
                [org_id],
            )
            lmqa_audit.append(
                conn,
                org_id=org_id,
                actor_id=actor_id,
                action="org.restored",
                target_type="organization",
                target_id=org_id,
                payload={},
            )
