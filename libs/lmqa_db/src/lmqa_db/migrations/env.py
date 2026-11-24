"""Alembic environment (KD-12, blueprint 4.5 and 18). The reviewed SQL in `db/migrations/` stays the source of
truth: each revision in `versions/` executes one file with `op.execute`. There is no ORM metadata, so
`--autogenerate` is not supported.

Connections run as `lmqa_owner`. `lmqa_db.migrate` passes an open connection in `config.attributes`; the CLI
(`alembic -c libs/lmqa_db/alembic.ini upgrade head`) builds one from settings, with `-x database=NAME` to target a
database other than `LMQA_DB_NAME`.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from lmqa_models.settings import load_settings

config = context.config


def sqlalchemy_url(database: str | None = None) -> str:
    """`lmqa_owner` DSN for the psycopg 3 driver."""
    dsn = load_settings().dsn("lmqa_owner", database=database)
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def _run(connection: object) -> None:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    database = context.get_x_argument(as_dictionary=True).get("database")
    engine = create_engine(sqlalchemy_url(database), poolclass=NullPool)
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    raise SystemExit("offline (--sql) mode is not supported: run `make migrate`")
run_online()
