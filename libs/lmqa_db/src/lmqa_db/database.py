"""Connection pools for the two runtime roles.

`scoped(user_id)` opens a transaction on `lmqa_app` (NOBYPASSRLS) and sets `app.user_id` with
`set_config(..., true)`, which is transaction-local: a pooled connection never carries one principal's
context into the next transaction, and with no context every content table returns zero rows (G1.3, G1.7).
`system()` uses `lmqa_system` for identity, onboarding and the ingestion worker, where authorization is
checked in code before any statement runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from lmqa_models.settings import Settings

Row = dict[str, Any]


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
    def __init__(self, settings: Settings, *, database: str | None = None) -> None:
        db = database or settings.db_name
        kwargs = {"row_factory": dict_row}
        self._app = ConnectionPool(
            settings.dsn("lmqa_app", database=db), min_size=1, max_size=8, kwargs=kwargs, open=False
        )
        self._system = ConnectionPool(
            settings.dsn("lmqa_system", database=db), min_size=1, max_size=8, kwargs=kwargs, open=False
        )

    def open(self) -> None:
        self._app.open(wait=True, timeout=10)
        self._system.open(wait=True, timeout=10)

    def close(self) -> None:
        self._app.close()
        self._system.close()

    @contextmanager
    def scoped(self, user_id: str) -> Iterator[Scope]:
        with self._app.connection() as conn, conn.transaction():
            conn.execute("select set_config('app.user_id', %s, true)", [str(user_id)])
            yield Scope(conn, str(user_id))

    @contextmanager
    def system(self) -> Iterator[psycopg.Connection[Row]]:
        with self._system.connection() as conn, conn.transaction():
            yield conn
