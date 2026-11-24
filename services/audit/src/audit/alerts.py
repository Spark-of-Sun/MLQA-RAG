"""Detection signals and alert delivery (blueprint 13.6, G9.3).

Signals are written as rows in `alerts` by the component that observes them (gateway 404 bursts, identity code
failures, reconciler scope mismatches, KeyGuard responder, chain verification). This module adds the periodic
checks that need a query, and delivers open alerts to the on-call webhook (`ONCALL_WEBHOOK_URL`); delivery is
retried until it succeeds and each alert is delivered once (dedup key).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

ConnFactory = Callable[[], AbstractContextManager[Any]]

CHECKS: dict[str, tuple[str, str]] = {
    # rule: (severity, SQL returning org_id, workspace_id, summary, dedup_key)
    "code_failure_burst": (
        "warning",
        """
        select null::uuid as org_id, null::uuid as workspace_id,
               'burst of failed join-code attempts from one address' as summary,
               'code_failure_burst:' || encode(ip_hash, 'hex') || ':' || to_char(now(), 'YYYYMMDDHH24') as dedup_key
        from join_attempts where outcome = 'rejected' and created_at > now() - interval '10 minutes'
        group by ip_hash having count(*) >= 20""",
    ),
    "admin_pending_too_long": (
        "warning",
        """
        select m.org_id, m.workspace_id, 'an admin has waited more than 7 days for approval' as summary,
               'admin_pending:' || m.id as dedup_key
        from memberships m where m.role = 'admin' and m.status in ('pending', 'pending_approval')
          and m.created_at < now() - interval '7 days'""",
    ),
    "break_glass_active": (
        "page",
        """
        select b.org_id, b.workspace_id, 'a break-glass session is active' as summary,
               'break_glass:' || b.id as dedup_key
        from break_glass_sessions b where b.state = 'active'""",
    ),
    "emergency_active": (
        "page",
        """
        select e.org_id, e.workspace_id, 'an emergency access session is active' as summary,
               'emergency:' || e.id as dedup_key
        from access_exceptions e where e.state = 'active'""",
    ),
    "operator_session_active": (
        "page",
        """
        select g.org_id, g.workspace_id, 'an operator access session is active' as summary,
               'operator:' || g.id as dedup_key
        from ops.operator_access_grants g where g.state = 'active'""",
    ),
    "outbox_dead": (
        "warning",
        """
        select o.org_id, o.workspace_id, 'vector index updates are failing' as summary,
               'outbox_dead:' || o.id as dedup_key
        from index_outbox o where o.state = 'dead'""",
    ),
}


class Alerting:
    def __init__(self, conn: ConnFactory, webhook_url: str | None) -> None:
        if webhook_url and not webhook_url.startswith("https://"):
            raise ValueError("ONCALL_WEBHOOK_URL must be an https URL")
        self._conn = conn
        self._webhook = webhook_url

    def evaluate(self) -> int:
        n = 0
        with self._conn() as conn:
            for rule, (severity, sql) in CHECKS.items():
                for r in conn.execute(sql).fetchall():
                    n += conn.execute(
                        "insert into alerts (org_id, workspace_id, rule, severity, summary, dedup_key)"
                        " values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
                        [
                            r["org_id"],
                            r["workspace_id"],
                            rule,
                            severity,
                            r["summary"],
                            r["dedup_key"],
                        ],
                    ).rowcount
            bad = conn.execute(
                "select o.id from organizations o, lateral audit_verify(o.id) v where not v.ok"
            ).fetchall()
            for r in bad:
                n += conn.execute(
                    "insert into alerts (org_id, rule, severity, summary, dedup_key) values (%s, 'audit_chain_failed',"
                    " 'page', 'audit chain verification failed', %s) on conflict do nothing",
                    [r["id"], f"audit_chain_failed:{r['id']}"],
                ).rowcount
        return n

    def deliver(self) -> int:
        if not self._webhook:
            return 0
        sent = 0
        with self._conn() as conn:
            rows = conn.execute(
                "select * from alerts where state = 'open' order by id limit 100 for update skip locked"
            ).fetchall()
            for r in rows:
                body = json.dumps(
                    {
                        "rule": r["rule"],
                        "severity": r["severity"],
                        "summary": r["summary"],
                        "org_id": str(r["org_id"]) if r["org_id"] else None,
                        "created_at": r["created_at"].isoformat(),
                    }
                ).encode()
                req = urllib.request.Request(  # noqa: S310 - webhook URL comes from operator config
                    self._webhook,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                try:
                    urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 - webhook URL comes from operator config
                except OSError:
                    continue
                conn.execute(
                    "update alerts set state = 'delivered', delivered_at = now() where id = %s",
                    [r["id"]],
                )
                sent += 1
        return sent
