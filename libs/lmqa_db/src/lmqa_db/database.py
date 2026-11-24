"""The in-process facade the MVP services share (DEV-01: one Gateway process hosts several services).

`scoped(user_id)` opens a transaction on `lmqa_app` (NOBYPASSRLS) and sets `app.user_id` with
`set_config(..., true)`, which is transaction-local: a pooled connection never carries one principal's
context into the next transaction, and with no context every content table returns zero rows (G1.3, G1.7).

`as_service(name, claims)` is `lmqa_db.scoped(pool, claims)` on that service's own NOBYPASSRLS role
(`lmqa_db.connect(name)`). There is no BYPASSRLS pool: identity, ingestion and audit each run as their own role
and the policies decide rows (KD-2, DEV-13).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lmqa_models.settings import Settings

if TYPE_CHECKING:
    from lmqa_db.service import ServiceDatabase

Row = dict[str, Any]

# Services the shared facade opens a pool for; each connects as its own role (lmqa_db.pool.SERVICE_ROLES).
FACADE_SERVICES = ("identity", "ingestion", "audit")


class Scope:
    """A transaction bound to one principal under row-level security."""

    def __init__(self, conn: psycopg.Connection[Row], user_id: str) -> None:
        self.conn = conn
        self.user_id = user_id

    def execute(self, query: Any, params: Any = None) -> psycopg.Cursor[Row]:
        return self.conn.execute(query, params)

    def cursor(self) -> psycopg.Cursor[Row]:
        return self.conn.cursor()


class Database:
    def __init__(
        self,
        settings: Settings,
        *,
        database: str | None = None,
        services: tuple[str, ...] = FACADE_SERVICES,
    ) -> None:
        from lmqa_db.pool import connect

        db = database or settings.db_name
        self._app = ConnectionPool(
            settings.dsn("lmqa_app", database=db),
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        self._services: dict[str, ServiceDatabase] = {
            name: connect(name, settings, database=db) for name in services
        }

    def open(self) -> None:
        self._app.open(wait=True, timeout=10)
        for pool in self._services.values():
            pool.open()  # runs the boot self-test (G1.3): a role that can bypass RLS refuses to start

    def close(self) -> None:
        self._app.close()
        for pool in self._services.values():
            pool.close()

    def service(self, name: str) -> ServiceDatabase:
        try:
            return self._services[name]
        except KeyError:
            raise ValueError(f"this Database has no pool for service {name!r}") from None

    @contextmanager
    def as_service(self, name: str, claims: Any) -> Iterator[psycopg.Connection[Row]]:
        from lmqa_db.pool import scoped

        with scoped(self.service(name), claims) as conn:
            yield conn

    def ping(self) -> None:
        with self._app.connection() as conn:
            conn.execute("select 1")

    @contextmanager
    def scoped(self, user_id: str) -> Iterator[Scope]:
        with self._app.connection() as conn, conn.transaction():
            conn.execute("select set_config('app.user_id', %s, true)", [str(user_id)])
            yield Scope(conn, str(user_id))
