"""Direct connections for tools, migrations, workers and tests (blueprint 4.7, 4.8).

Request-path code never uses this: it runs statements only through
`lmqa_db.scoped(pool, claims)`. Direct connections exist for
callers that need session state the transaction pooler cannot keep (migrations, `LISTEN`/`NOTIFY` workers, session
advisory locks) and for the doctor and the gate suites. `via_pooler=True` connects through PgBouncer instead, the
way the request path does.
"""

from __future__ import annotations

from typing import Any

import psycopg

from lmqa_models.infra import InfraSettings, load_infra_settings
from lmqa_models.settings import Settings

# Request-path roles. Migrations (lmqa_owner) and superusers always connect directly.
POOLED_ROLES = frozenset(
    {
        "lmqa_app",
        "svc_gateway",
        "svc_retrieval",
        "svc_generation",
        "svc_validator",
        "svc_identity",
        "svc_ingestion",
        "svc_audit_reader",
        "svc_ops",
    }
)


def dsn(
    settings: Settings,
    role: str,
    *,
    database: str | None = None,
    via_pooler: bool = False,
    infra: InfraSettings | None = None,
) -> str:
    """A libpq URL for `role`; through PgBouncer when `via_pooler` (runtime roles only)."""
    if not via_pooler:
        return settings.dsn(role, database=database)
    if role not in POOLED_ROLES:
        raise ValueError(f"role {role} does not connect through the pooler")
    infra = infra or load_infra_settings()
    return settings.dsn(
        role, database=database, host=infra.pgbouncer_host, port=infra.pgbouncer_port
    )


def connect_role(
    settings: Settings,
    role: str,
    *,
    database: str | None = None,
    via_pooler: bool = False,
    autocommit: bool = False,
    **kwargs: Any,
) -> psycopg.Connection[Any]:
    """Open one direct connection. The caller closes it (use it as a context manager)."""
    return psycopg.connect(
        dsn(settings, role, database=database, via_pooler=via_pooler),
        autocommit=autocommit,
        **kwargs,
    )
