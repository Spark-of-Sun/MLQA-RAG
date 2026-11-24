"""Workspace-month audit keys created ahead of time (KD-10, R-51.2, R-60.2).

`lmqa_audit.append` seals a payload to the active audit key of its chain for the current UTC month and fails closed
when that month has no key. `provision_audit_keys` therefore creates, for every organization control chain and every
workspace chain that can still be written to, the key pair of the current month and of the next month, so a sealed
write at a month boundary always finds its key. It is idempotent: it creates only the pairs that have no row for that
month, and never re-creates a month whose key was retired or shredded. The identity worker runs it on every loop.

The caller supplies `transaction`, a factory for one database transaction on a role that may insert into
`audit_keys` and `org_keys` (the identity role). Each key is created in its own transaction, so one key-provider
failure leaves the other keys in place; the failure is reported, not raised, and the next loop retries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from lmqa_keys.keyring import Conn, KeyRing
from lmqa_keys.providers import KeyProviderError

log = logging.getLogger("lmqa_keys.audit_keys")

# Chains that can no longer be written to get no new keys.
CLOSED_ORG_STATES = ("rejected", "destroyed")
CLOSED_WORKSPACE_STATES = ("rejected", "destroyed")

# Organizations without a CMK are left to their provisioning saga, which creates the CMK and the first keys.
MISSING_SQL = """
select o.id as org_id, null::uuid as workspace_id, m.month
  from organizations o cross join unnest(%(months)s::date[]) as m(month)
 where o.status <> all(%(closed_org)s)
   and exists (select 1 from org_keys ok where ok.org_id = o.id)
   and not exists (select 1 from audit_keys k
                    where k.org_id = o.id and k.workspace_id is null and k.month = m.month)
union all
select w.org_id, w.id as workspace_id, m.month
  from workspaces w join organizations o on o.id = w.org_id cross join unnest(%(months)s::date[]) as m(month)
 where o.status <> all(%(closed_org)s) and w.status <> all(%(closed_ws)s)
   and exists (select 1 from org_keys ok where ok.org_id = o.id)
   and not exists (select 1 from audit_keys k
                    where k.org_id = w.org_id and k.workspace_id = w.id and k.month = m.month)
 order by 1, 2 nulls first, 3
"""


def provision_months(today: date) -> list[date]:
    """The first day of the current month and of the next month."""
    current = date(today.year, today.month, 1)
    following = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    return [current, following]


# (org_id, workspace_id or None for the control chain, month)
Failure = tuple[str, str | None, date]


@dataclass
class AuditKeyProvisioning:
    created: int = 0
    failed: list[Failure] = field(default_factory=list[Failure])


def provision_audit_keys(
    transaction: Callable[[], AbstractContextManager[Conn]],
    ring: KeyRing,
    today: date | None = None,
) -> AuditKeyProvisioning:
    """Create the missing current-month and next-month audit keys of every writable chain."""
    months = provision_months(today or datetime.now(UTC).date())
    with transaction() as conn:
        missing: list[Any] = conn.execute(
            MISSING_SQL,
            {
                "months": months,
                "closed_org": list(CLOSED_ORG_STATES),
                "closed_ws": list(CLOSED_WORKSPACE_STATES),
            },
        ).fetchall()
    out = AuditKeyProvisioning()
    for row in missing:
        org_id = str(row["org_id"])
        workspace_id = str(row["workspace_id"]) if row["workspace_id"] else None
        try:
            with transaction() as conn:
                ring.ensure_audit_key(conn, org_id, workspace_id, row["month"])
            out.created += 1
        except KeyProviderError as exc:
            out.failed.append((org_id, workspace_id, row["month"]))
            log.warning(
                "audit key for %s/%s/%s not created: %s",
                org_id,
                workspace_id or "control",
                row["month"],
                type(exc).__name__,
            )
    return out
