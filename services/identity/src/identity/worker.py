"""identity-worker (blueprint 4.2): saga steps, governance clock, expiry sweeps, notifications, Auth0 sync, and the
current and next month's audit keys of every writable chain, created ahead of the month boundary (KD-10).

Runs on a direct database connection (session state allowed) as the identity role. Each loop is idempotent, so any
number of workers may run; row locks with SKIP LOCKED keep them from doing the same work twice.

    python -m identity.worker [--once]
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from identity.auth0_mgmt import Auth0Management, config_from_env
from identity.destruction import (
    Lifecycle,
    org_delete_effect,
    workspace_destroy_effect_factory,
    workspace_unseal_effect_factory,
)
from identity.governance import GovernanceService
from identity.lifecycle import (
    Notifier,
    co_owner_set_effect,
    reconcile_auth0_roles,
    smtp_from_env,
    successor_transfer_effect,
)
from identity.saga import OrganizationSaga
from identity.scope_admin import ScopeAdmin
from lmqa_db import Claims, Database
from lmqa_keys import KeyRing, provider_from_settings, provision_audit_keys
from lmqa_models.envfile import merged_env
from lmqa_models.policy import load_policy
from lmqa_models.settings import load_settings
from lmqa_security.redact import configure_logging

log = logging.getLogger("identity.worker")
RECONCILE_EVERY = 3600.0


def build() -> dict[str, Any]:
    settings = load_settings()
    env = merged_env()
    db = Database(settings, services=("identity",))
    db.open()

    @contextmanager
    def conn() -> Iterator[Any]:
        with db.as_service("identity", Claims(actor="identity:worker")) as c:
            yield c

    policy = load_policy()
    provider = provider_from_settings(region=env.get("AWS_REGION"))
    keyring = KeyRing(provider)
    cfg = config_from_env(env)
    auth0 = Auth0Management(cfg) if cfg and env.get("AUTH0_ORGANIZATIONS", "off") == "on" else None
    governance = GovernanceService(
        conn,
        policy,
        {
            "wall_lift": ScopeAdmin.lift_wall_effect,
            "private_read_enable": ScopeAdmin.private_read_enable_effect,
            "successor_transfer": successor_transfer_effect,
            "co_owner_set": co_owner_set_effect,
            "org_delete": org_delete_effect,
            "workspace_destroy": workspace_destroy_effect_factory(keyring),
            "workspace_unseal": workspace_unseal_effect_factory(keyring, None),
        },
    )
    return {
        "db": db,
        "conn": conn,
        "keyring": keyring,
        "governance": governance,
        "scope": ScopeAdmin(conn, policy, Notifier.enqueue),
        "notifier": Notifier(conn, smtp_from_env(env)),
        "auth0": auth0,
        "lifecycle": Lifecycle(conn, policy, keyring, provider),
        "saga": OrganizationSaga(
            conn,
            provider,
            auth0,
            alias_prefix=env.get("KMS_ORG_KEY_ALIAS_PREFIX", "alias/lmqa-dev-org-"),
        ),
    }


def run_once(parts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "governance": parts["governance"].tick(),
        "sweep": parts["scope"].sweep(),
        "mail": parts["notifier"].deliver(),
        "lifecycle": parts["lifecycle"].tick(),
    }
    keys = provision_audit_keys(parts["conn"], parts["keyring"])
    out["audit_keys"] = {"created": keys.created, "failed": len(keys.failed)}
    with parts["conn"]() as conn:
        stuck = conn.execute(
            "select id from provisioning_sagas where state = 'running' and updated_at < now() - interval '1 minute'"
        ).fetchall()
    out["sagas"] = [parts["saga"].resume(str(r["id"])).state for r in stuck]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args()
    configure_logging(logging.INFO)
    parts = build()
    last_reconcile = 0.0
    try:
        while True:
            log.info("identity worker: %s", run_once(parts))
            if parts["auth0"] and time.monotonic() - last_reconcile > RECONCILE_EVERY:
                findings = reconcile_auth0_roles(parts["conn"], parts["auth0"])
                log.info("auth0 reconciliation: %d finding(s)", len(findings))
                last_reconcile = time.monotonic()
            if args.once:
                return 0
            time.sleep(args.interval)
    finally:
        parts["db"].close()


if __name__ == "__main__":
    raise SystemExit(main())
