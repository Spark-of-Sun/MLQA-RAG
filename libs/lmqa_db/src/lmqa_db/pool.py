"""One pool per service role, and `scoped(pool, claims)` (blueprint 9.2, 10.3, 16.3; KD-2, DEV-13).

`connect(service)` returns the pool of that service's own login role. Every role is NOBYPASSRLS and owns no table, so
FORCE ROW LEVEL SECURITY and the policies in `db/policies` decide rows for every statement, whichever code path
issues it. There is no BYPASSRLS pool any more (`lmqa_system` is gone from every runtime path).

`scoped(pool, claims)` opens one transaction and writes the claims as transaction-local settings
(`set_config('app.<name>', value, true)`, the function form of `SET LOCAL app.<name>`). A pooled connection never
carries one principal's context into the next transaction, and with no `app.user_id` every content policy is false.
It refuses to run without claims: a caller that has no user (a login lookup, a worker) names itself in `actor`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import psycopg

from lmqa_db.database import Row
from lmqa_db.service import ServiceDatabase, StalePrincipalError
from lmqa_models.settings import Settings, load_settings

# service -> its login role (db/roles/grants.sql). Names follow DB_SERVICE_ROLES in lmqa_models.settings.
SERVICE_ROLES: dict[str, str] = {
    "gateway": "svc_gateway",
    "identity": "svc_identity",
    "ingestion": "svc_ingestion",
    "retrieval": "svc_retrieval",
    "generation": "svc_generation",
    "validator": "svc_validator",
    "audit": "svc_audit_reader",
    "reconciler": "svc_reconciler",
    "ops": "svc_ops",
    "ops_metadata": "ops_metadata_ro",
}

_SETTING = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class MissingContextError(RuntimeError):
    """A scoped transaction was requested without claims (R-32 criterion 3)."""


@dataclass(frozen=True)
class Claims:
    """What one scoped transaction writes as `app.*` settings. `user_id` is the principal; `actor` names a caller
    that acts without one (it matches no content row: policies read only `app.user_id`)."""

    user_id: UUID | None = None
    request_id: UUID | str | None = None
    principal_version: int | None = None
    actor: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, who: Claims | Any) -> Claims:
        """Claims from a Claims, a principal-like object (`.user_id`), or a user id."""
        if isinstance(who, Claims):
            return who
        if who is None:
            raise MissingContextError("scoped() needs claims: a user id or an actor")
        uid = getattr(who, "user_id", who)
        return cls(user_id=UUID(str(uid)))

    def settings(self) -> dict[str, str]:
        if self.user_id is None and not self.actor:
            raise MissingContextError("claims carry neither a user id nor an actor")
        values = {
            "user_id": str(self.user_id or ""),
            "request_id": str(self.request_id or ""),
            "actor": self.actor or "",
            **dict(self.extra),
        }
        for name in values:
            if not _SETTING.match(name):
                raise ValueError(f"invalid context setting name {name!r}")
        return values


def connect(
    service: str,
    settings: Settings | None = None,
    *,
    database: str | None = None,
    via_pooler: bool = False,
    max_size: int = 8,
) -> ServiceDatabase:
    """The (unopened) pool of `service`'s own role. The password comes from settings by name
    (`LMQA_DB_<ROLE>_PASSWORD`), never from code."""
    try:
        role = SERVICE_ROLES[service]
    except KeyError:
        raise ValueError(f"unknown service {service!r}; known: {sorted(SERVICE_ROLES)}") from None
    return ServiceDatabase(
        settings or load_settings(),
        role,
        via_pooler=via_pooler,
        max_size=max_size,
        database=database,
    )


@contextmanager
def scoped(pool: ServiceDatabase, claims: Claims | Any) -> Iterator[psycopg.Connection[Row]]:
    """One transaction on `pool` with `claims` set transaction-locally. Yields the connection."""
    values = Claims.of(claims).settings()
    with pool.connection() as conn, conn.transaction():
        for name, value in values.items():
            conn.execute("select set_config(%s, %s, true)", [f"app.{name}", value])
        pv = claims.principal_version if isinstance(claims, Claims) else None
        if pv is not None:
            row = conn.execute("select app_principal_version() as pv").fetchone()
            if not row or row["pv"] != pv:
                raise StalePrincipalError("principal changed since the context token was minted")
        yield conn
