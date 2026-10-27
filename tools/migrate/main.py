"""Run database migrations and initialize service roles."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg
from lmqa_db import DatabaseConfig

DEFAULT_PGBOUNCER_PORT = 6432
DEFAULT_POSTGRES_PORT = 5432


def _load_sql_files(directory: Path) -> list[tuple[str, str]]:
    """Synchronously load and return list of (name, sql_text) tuples."""
    if not directory.is_dir():
        return []
    items: list[tuple[str, str]] = []
    for sql_file in sorted(directory.glob("*.sql")):
        sql = sql_file.read_text(encoding="utf-8")
        items.append((sql_file.name, sql))
    return items


async def _apply_sql_payloads(
    conn: asyncpg.Connection, payloads: list[tuple[str, str]], label: str
) -> None:
    """Apply pre-loaded SQL payloads in order."""
    for name, sql in payloads:
        print(f"Applying {label}: {name}...")
        await conn.execute(sql)
        print(f"  -> Applied {name}")


async def _verify_force_rls(conn: asyncpg.Connection) -> bool:
    """Verify that FORCE ROW LEVEL SECURITY is active on all public tables."""
    print("\nVerifying FORCE ROW LEVEL SECURITY on all public tables...")
    query = """
        SELECT c.relname AS tablename,
               c.relrowsecurity AS rowsecurity,
               c.relforcerowsecurity AS forcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname;
    """
    rows = await conn.fetch(query)
    if not rows:
        print("WARNING: No public tables found.")
        return False

    all_forced = True
    for r in rows:
        table = r["tablename"]
        rls = r["rowsecurity"]
        forced = r["forcerowsecurity"]
        status = "✅ FORCE RLS" if (rls and forced) else "❌ NOT FORCED"
        print(f"  Table: {table:<22} -> {status}")
        if not (rls and forced):
            all_forced = False

    return all_forced


async def _execute_migrations_async(
    cfg: DatabaseConfig,
    migration_payloads: list[tuple[str, str]],
    role_payloads: list[tuple[str, str]],
) -> int:
    """Execute pre-loaded migrations over asyncpg connection."""
    host = cfg.host
    port = DEFAULT_POSTGRES_PORT if cfg.port == DEFAULT_PGBOUNCER_PORT else cfg.port
    print(f"Connecting to PostgreSQL at {host}:{port}/{cfg.database} as {cfg.user}...")

    conn = None
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=cfg.user,
            password=cfg.password or "lmqa_secret",
            database=cfg.database,
            timeout=10,
        )
    except (OSError, asyncpg.PostgresError) as e:
        print(f"ERROR: Failed to connect to PostgreSQL: {e}")
        return 1

    try:
        await _apply_sql_payloads(conn, migration_payloads, "migration")
        await _apply_sql_payloads(conn, role_payloads, "roles")

        rls_passed = await _verify_force_rls(conn)
        if not rls_passed:
            print("ERROR: One or more tables do not have FORCE ROW LEVEL SECURITY enabled!")
            return 1
    except asyncpg.PostgresError as e:
        print(f"ERROR: Database migration step failed: {e}")
        return 1
    finally:
        if conn:
            await conn.close()

    print("\nDatabase configuration and migrations completed successfully!")
    return 0


def run_migrations() -> int:
    """Synchronously load files and run async database migration."""
    cfg = DatabaseConfig.from_env()
    root_dir = Path(__file__).resolve().parent.parent.parent
    migrations_dir = root_dir / "db" / "migrations"
    roles_dir = root_dir / "db" / "roles"

    migration_payloads = _load_sql_files(migrations_dir)
    role_payloads = _load_sql_files(roles_dir)

    return asyncio.run(_execute_migrations_async(cfg, migration_payloads, role_payloads))


def main() -> None:
    """CLI entrypoint for migration tool."""
    code = run_migrations()
    sys.exit(code)


if __name__ == "__main__":
    main()
