"""Alembic environment: synchronous psycopg connection from PG_MIGRATION_DSN."""

import os

from alembic import context
from sqlalchemy import create_engine, pool


def _url() -> str:
    dsn = os.environ.get("PG_MIGRATION_DSN")
    if not dsn:
        msg = "PG_MIGRATION_DSN is not set (see .env.example)"
        raise RuntimeError(msg)
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema="alembic_meta",
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
