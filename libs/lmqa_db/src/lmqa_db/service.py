"""Per-service database access for the production services (blueprint 9.2, 10.3, 10.10, 16.3).

`ServiceDatabase` connects as the service's own NOBYPASSRLS role, through PgBouncer on the request path. It runs the
boot self-test before serving (G1.3): any table without FORCE ROW LEVEL SECURITY, any service role that can bypass
RLS or owns tables, or any PUBLIC table grant makes the service refuse to start.

`OrgRouter` picks the database cluster for an organization: pooled organizations share the default cluster; a
`silo` organization (contract tier, D5) has its own DSN (`PG_DSN_ORG_<org_id without dashes>`). The router never
falls back to the pooled cluster for a silo organization: a missing silo DSN is an error, not a downgrade.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lmqa_db.database import Row, Scope
from lmqa_db.direct import dsn as build_dsn
from lmqa_models.envfile import merged_env
from lmqa_models.settings import Settings


class StalePrincipalError(RuntimeError):
    """The caller's principal_version moved (suspension, role change): abort long work (G3.3)."""


class BootSelfTestError(RuntimeError):
    """The database does not enforce isolation as designed; the service must not start."""


@dataclass(frozen=True)
class ScopeContext:
    """What a scoped transaction sets, transaction-local (set_config(..., true)), never session state."""

    user_id: UUID
    request_id: UUID | None = None
    principal_version: int | None = None


class ServiceDatabase:
    def __init__(  # noqa: PLR0913 - one linear flow; splitting it is a DEV-33 follow-up
        self,
        settings: Settings,
        role: str,
        *,
        via_pooler: bool = True,
        max_size: int = 10,
        database: str | None = None,
        conninfo: str | None = None,
    ) -> None:
        self.role = role
        url = conninfo or build_dsn(settings, role, database=database, via_pooler=via_pooler)
        # prepare_threshold stays at psycopg's default: PgBouncer >= 1.21 tracks protocol-level prepared statements.
        self._pool = ConnectionPool(
            url, min_size=1, max_size=max_size, kwargs={"row_factory": dict_row}, open=False
        )

    def open(self, *, self_test: bool = True) -> None:
        self._pool.open(wait=True, timeout=10)
        if self_test:
            self.boot_self_test()

    def close(self) -> None:
        self._pool.close()

    def boot_self_test(self) -> None:
        with self._pool.connection() as conn, conn.transaction():
            problems = [
                r["problem"]
                for r in conn.execute("select problem from app_boot_self_test()").fetchall()
            ]
            # Roles without a documents grant (identity, audit) cannot leak content; probe only the others.
            can_read = conn.execute(
                "select has_table_privilege(current_user, 'documents', 'select') as ok"
            ).fetchone()
            leaked = (
                conn.execute(
                    "select count(*) as n from documents"
                    " where nullif(current_setting('app.user_id', true), '') is null"
                ).fetchone()
                if can_read and can_read["ok"]
                else None
            )
        if leaked and leaked["n"]:
            problems.append(f"{self.role} sees {leaked['n']} documents without a context")
        if problems:
            raise BootSelfTestError("; ".join(problems))

    @contextmanager
    def scoped(self, ctx: ScopeContext | UUID | str) -> Iterator[Scope]:
        if not isinstance(ctx, ScopeContext):
            ctx = ScopeContext(user_id=UUID(str(ctx)))
        with self._pool.connection() as conn, conn.transaction():
            conn.execute(
                "select set_config('app.user_id', %s, true), set_config('app.request_id', %s, true)",
                [str(ctx.user_id), str(ctx.request_id or "")],
            )
            if ctx.principal_version is not None:
                row = conn.execute("select app_principal_version() as pv").fetchone()
                if not row or row["pv"] != ctx.principal_version:
                    raise StalePrincipalError(
                        "principal changed since the context token was minted"
                    )
            yield Scope(conn, str(ctx.user_id))

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Row]]:
        """A raw pooled connection for `lmqa_db.scoped(pool, claims)`; callers never run statements on it
        without setting a context first."""
        with self._pool.connection() as conn:
            yield conn


class OrgRouter:
    """Organization -> database for the pooled and silo tiers (10.10)."""

    def __init__(
        self, settings: Settings, role: str, *, pooled: ServiceDatabase | None = None
    ) -> None:
        self._settings = settings
        self._role = role
        self._pooled = pooled or ServiceDatabase(settings, role)
        self._silos: dict[str, ServiceDatabase] = {}
        self._deployment: dict[str, str] = {}

    def open(self) -> None:
        self._pooled.open()

    def close(self) -> None:
        self._pooled.close()
        for db in self._silos.values():
            db.close()

    def register(self, org_id: UUID | str, deployment: str) -> None:
        self._deployment[str(org_id)] = deployment

    def for_org(self, org_id: UUID | str) -> ServiceDatabase:
        key = str(org_id)
        if self._deployment.get(key, "pooled") == "pooled":
            return self._pooled
        if key not in self._silos:
            env = merged_env()
            url = env.get(f"PG_DSN_ORG_{key.replace('-', '').upper()}")
            if not url:
                raise BootSelfTestError(
                    f"silo organization {key} has no PG_DSN_ORG_* setting; refusing to fall back"
                )
            db = ServiceDatabase(self._settings, self._role, conninfo=url)
            db.open()
            self._silos[key] = db
        return self._silos[key]
