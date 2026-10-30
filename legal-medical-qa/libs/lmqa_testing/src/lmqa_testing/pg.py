"""Real PostgreSQL for tests (doc 19.1, R2 and R5): no mocks, service roles only.

Tests build a fresh database with the real migrations and then connect as the real service
roles (``svc_identity``, ``svc_ingestion`` and so on), never as a superuser. Local test servers
use trust authentication; CI sets ``LMQA_TEST_PASSWORD_<ROLE>`` where passwords apply.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config

from lmqa_db import bootstrap_database
from lmqa_db.bootstrap import repo_root

if TYPE_CHECKING:
    from collections.abc import Generator


def _host() -> str:
    return os.environ.get("LMQA_TEST_PG_HOST", "127.0.0.1")


def _port() -> str:
    return os.environ.get("LMQA_TEST_PG_PORT", "5432")


def superuser_dsn() -> str:
    """DSN of the bootstrap superuser (create roles and databases only)."""
    default = f"host={_host()} port={_port()} user=postgres dbname=postgres"
    return os.environ.get("LMQA_TEST_SUPERUSER_DSN", default)


def role_dsn(role: str, dbname: str) -> str:
    """DSN for one service role, with a password only if the environment supplies one."""
    password = os.environ.get(f"LMQA_TEST_PASSWORD_{role.upper()}")
    auth = f"{role}:{password}" if password else role
    return f"postgresql://{auth}@{_host()}:{_port()}/{dbname}"


@contextmanager
def _env(name: str, value: str) -> Generator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def alembic_config() -> Config:
    """Alembic configuration pointing at ``db/``."""
    return Config(str(repo_root() / "db" / "alembic.ini"))


def migrate(dbname: str, revision: str = "head", *, downgrade: bool = False) -> None:
    """Run Alembic as ``lmqa_owner`` against ``dbname``."""
    with _env("PG_MIGRATION_DSN", role_dsn("lmqa_owner", dbname)):
        if downgrade:
            command.downgrade(alembic_config(), revision)
        else:
            command.upgrade(alembic_config(), revision)


def fresh_database(dbname: str) -> None:
    """Drop and recreate ``dbname`` with roles, ownership and every migration applied."""
    bootstrap_database(superuser_dsn(), dbname, reset=True)
    migrate(dbname)


def pooled_role_dsn(role: str, dbname: str) -> str:
    """DSN for one service role through PgBouncer (transaction pooling)."""
    port = os.environ.get("LMQA_TEST_PGBOUNCER_PORT", "6432")
    return role_dsn(role, dbname).replace(f":{_port()}/", f":{port}/")
