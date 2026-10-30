"""Database bootstrap: roles, database, schema ownership, passwords (doc 10.3).

Runs as a PostgreSQL superuser or a role with CREATEROLE and CREATEDB, once per environment.
Migrations then run as ``lmqa_owner``, a role no service holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

if TYPE_CHECKING:
    from collections.abc import Mapping

LOGIN_ROLES = (
    "svc_gateway",
    "svc_identity",
    "svc_ingestion",
    "svc_retrieval",
    "svc_generation",
    "svc_validator",
    "svc_audit_reader",
    "svc_reconciler",
    "svc_ops",
    "ops_metadata_ro",
)


def repo_root() -> Path:
    """Locate the repository root (the directory that holds ``db/roles``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "db" / "roles" / "001_roles.sql").is_file():
            return parent
    msg = "repository root with db/roles/001_roles.sql not found"
    raise FileNotFoundError(msg)


def with_database(dsn: str, dbname: str) -> str:
    """Return ``dsn`` pointing at ``dbname`` (libpq keyword/value or URL form)."""
    return make_conninfo(dsn, dbname=dbname)


def bootstrap_database(superuser_dsn: str, dbname: str, *, reset: bool = False) -> None:
    """Create roles, the database and schema ownership. Idempotent unless ``reset`` is set."""
    roles_sql = (repo_root() / "db" / "roles" / "001_roles.sql").read_text(encoding="utf-8")
    with psycopg.connect(with_database(superuser_dsn, "postgres"), autocommit=True) as admin:
        if reset:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname))
            )
        admin.execute(roles_sql)  # type: ignore[arg-type]
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER lmqa_owner").format(sql.Identifier(dbname))
            )
        admin.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname))
        )
        for role in (*LOGIN_ROLES, "lmqa_owner"):
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(dbname), sql.Identifier(role)
                )
            )
    with psycopg.connect(with_database(superuser_dsn, dbname), autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS alembic_meta AUTHORIZATION lmqa_owner")
        conn.execute("ALTER SCHEMA public OWNER TO lmqa_owner")
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        _install_pooler_auth(conn)


def _install_pooler_auth(conn: psycopg.Connection) -> None:
    """Create ``pgbouncer.get_auth`` so PgBouncer can authenticate service roles (doc 10.3).

    The function can return the password verifier of the platform's own login roles only.
    """
    roles = ", ".join(f"'{r}'" for r in (*LOGIN_ROLES, "lmqa_owner"))
    conn.execute("CREATE SCHEMA IF NOT EXISTS pgbouncer AUTHORIZATION postgres")
    conn.execute(
        "CREATE OR REPLACE FUNCTION pgbouncer.get_auth(p_usename text)"  # noqa: S608
        " RETURNS TABLE (usename name, passwd text) LANGUAGE sql SECURITY DEFINER"
        " SET search_path = pg_catalog AS $$"
        " SELECT s.usename, s.passwd FROM pg_catalog.pg_shadow s"
        f" WHERE s.usename = p_usename AND s.usename IN ({roles})"
        " $$"
    )
    conn.execute("REVOKE ALL ON FUNCTION pgbouncer.get_auth(text) FROM PUBLIC")
    conn.execute("GRANT USAGE ON SCHEMA pgbouncer TO pgbouncer_auth")
    conn.execute("GRANT EXECUTE ON FUNCTION pgbouncer.get_auth(text) TO pgbouncer_auth")


def set_role_passwords(superuser_dsn: str, passwords: Mapping[str, str]) -> None:
    """Set login passwords from the environment. Role names are validated against a fixed list."""
    allowed = {*LOGIN_ROLES, "lmqa_owner", "pgbouncer_auth"}
    with psycopg.connect(with_database(superuser_dsn, "postgres"), autocommit=True) as admin:
        for role, password in passwords.items():
            if role not in allowed:
                msg = f"refusing to set a password for unknown role {role!r}"
                raise ValueError(msg)
            admin.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
