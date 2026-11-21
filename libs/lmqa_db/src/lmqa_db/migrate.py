"""Create roles and the database, then apply `db/` in order (blueprint 18):

  db/migrations/*.sql   schema, applied once each, tracked in schema_migrations
  db/policies/*.sql     helper functions, RLS policies, audit functions: idempotent, re-applied every run
  db/roles/grants.sql   least-privilege grants: idempotent, re-applied every run

Roles (created here because they need passwords from settings):
  lmqa_owner   owns the schema, runs migrations, never used at runtime
  lmqa_app     data plane, NOBYPASSRLS: sees content only through row-level security
  lmqa_system  identity, onboarding, ingestion worker: BYPASSRLS, authorization enforced in code
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg import sql

from lmqa_models.envfile import ROOT
from lmqa_models.settings import Settings

DB_DIR = ROOT / "db"
ROLES = {"lmqa_owner": False, "lmqa_app": False, "lmqa_system": True}  # role -> BYPASSRLS


def _password(settings: Settings, role: str) -> str:
    value = {
        "lmqa_owner": settings.db_owner_password,
        "lmqa_app": settings.db_app_password,
        "lmqa_system": settings.db_system_password,
    }[role]
    if not value:
        raise RuntimeError(f"Password for {role} is not set. Run: make setup")
    return value


def bootstrap(settings: Settings, database: str) -> None:
    """Idempotently create roles, the database and the vector extension (superuser, local only)."""
    with psycopg.connect(settings.dsn("postgres"), autocommit=True) as conn, conn.cursor() as cur:
        for role, bypass in ROLES.items():
            cur.execute("select 1 from pg_roles where rolname = %s", [role])
            verb = "alter" if cur.fetchone() else "create"
            cur.execute(
                sql.SQL("{} role {} with login nosuperuser nocreatedb nocreaterole {} password {}").format(
                    sql.SQL(verb),
                    sql.Identifier(role),
                    sql.SQL("bypassrls" if bypass else "nobypassrls"),
                    sql.Literal(_password(settings, role)),
                )
            )
        cur.execute("select 1 from pg_database where datname = %s", [database])
        if not cur.fetchone():
            cur.execute(sql.SQL("create database {} owner lmqa_owner").format(sql.Identifier(database)))
    with psycopg.connect(settings.dsn("postgres", database=database), autocommit=True) as conn:
        conn.execute("create extension if not exists vector")
        conn.execute("revoke all on schema public from public")
        conn.execute("grant all on schema public to lmqa_owner")


def _run_file(conn: psycopg.Connection, path: Path) -> None:
    conn.execute(path.read_text(encoding="utf-8"))  # type: ignore[arg-type]


def apply(settings: Settings, database: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(settings.dsn("lmqa_owner", database=database)) as conn:
        conn.execute(
            "create table if not exists schema_migrations"
            " (name text primary key, applied_at timestamptz not null default now())"
        )
        done = {row[0] for row in conn.execute("select name from schema_migrations")}
        for path in sorted((DB_DIR / "migrations").glob("*.sql")):
            if path.name not in done:
                with conn.transaction():
                    _run_file(conn, path)
                    conn.execute("insert into schema_migrations (name) values (%s)", [path.name])
                applied.append(path.name)
        with conn.transaction():
            for path in sorted((DB_DIR / "policies").glob("*.sql")):
                _run_file(conn, path)
            _run_file(conn, DB_DIR / "roles" / "grants.sql")
    return applied


def drop_database(settings: Settings, database: str) -> None:
    with psycopg.connect(settings.dsn("postgres"), autocommit=True) as conn:
        conn.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(database)))


def migrate(settings: Settings, database: str | None = None) -> list[str]:
    db = database or settings.db_name
    bootstrap(settings, db)
    return apply(settings, db)
