"""Create roles, the database and the schema, set role passwords from the environment, run migrations.

Run once per environment (and again after every release that adds a migration):

    uv run python tools/db_migrate.py

It connects as a PostgreSQL superuser (``POSTGRES_SUPERUSER_DSN``) ONLY to create roles and the
database; migrations then run as ``lmqa_owner``, a role no service holds, directly against
PostgreSQL (never through the pooler). Passwords come from the same ``PG_DSN_*`` values the services
use, so a service can never hold a credential the bootstrap did not set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from alembic import command
from alembic.config import Config

from lmqa_db import LOGIN_ROLES, bootstrap_database, set_role_passwords
from lmqa_db.bootstrap import repo_root

ROLE_FOR_ENV = {
    "PG_MIGRATION_DSN": "lmqa_owner",
    "PG_DSN_GATEWAY": "svc_gateway",
    "PG_DSN_IDENTITY": "svc_identity",
    "PG_DSN_INGESTION": "svc_ingestion",
    "PG_DSN_RETRIEVAL": "svc_retrieval",
    "PG_DSN_GENERATION": "svc_generation",
    "PG_DSN_VALIDATOR": "svc_validator",
    "PG_DSN_AUDIT": "svc_audit_reader",
    "PG_DSN_OPS": "svc_ops",
    "PGBOUNCER_AUTH_DSN": "pgbouncer_auth",
}


def _password(dsn: str) -> str | None:
    pw = urlsplit(dsn).password
    return unquote(pw) if pw else None


def _load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    env_file = Path(os.environ.get("ENV_FILE", repo_root() / ".env"))
    if env_file.is_file():
        _load_env_file(env_file)
    superuser = os.environ.get("POSTGRES_SUPERUSER_DSN")
    owner_dsn = os.environ.get("PG_MIGRATION_DSN")
    if not superuser or not owner_dsn or owner_dsn.startswith("<"):
        print("Set POSTGRES_SUPERUSER_DSN and PG_MIGRATION_DSN (see .env.example).")
        return 2
    dbname = urlsplit(owner_dsn).path.lstrip("/") or "lmqa"
    passwords: dict[str, str] = {}
    for var, role in ROLE_FOR_ENV.items():
        value = os.environ.get(var, "")
        if value and not value.startswith("<") and (pw := _password(value)):
            passwords[role] = pw
    missing = {*LOGIN_ROLES, "lmqa_owner"} - set(passwords) - {"svc_reconciler", "ops_metadata_ro"}
    if missing:
        print(f"No password configured for: {', '.join(sorted(missing))}")
        return 2
    bootstrap_database(superuser, dbname)
    set_role_passwords(superuser, passwords)
    config = Config(str(repo_root() / "db" / "alembic.ini"))
    command.upgrade(config, "head")
    print(f"database {dbname!r} is at the latest migration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
