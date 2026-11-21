"""Boot self-test (doc 10.3): a service refuses to start unless isolation demonstrably holds.

Structural checks (the login role is not a superuser, does not bypass RLS and owns no table;
every table has FORCE ROW LEVEL SECURITY) and functional probes (a query with no context, and
a query with a context for a different workspace, both return zero rows).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lmqa_db.context import DbContext
    from lmqa_db.session import Database

_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class SelfTestError(RuntimeError):
    """Raised when the isolation self-test fails; the service must not start."""


async def _structural(db: Database) -> list[str]:
    problems: list[str] = []
    async with db.unscoped_for_self_test() as s:
        role = (
            await s.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, current_user AS name FROM pg_roles"
                    " WHERE rolname = current_user"
                )
            )
        ).one()
        if role.rolsuper or role.rolbypassrls:
            problems.append(f"role {role.name} is superuser or BYPASSRLS")
        owned = (
            (
                await s.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                        " AND tableowner = current_user"
                    )
                )
            )
            .scalars()
            .all()
        )
        if owned:
            problems.append(f"role {role.name} owns tables: {sorted(owned)}")
        unforced = (
            (
                await s.execute(
                    text(
                        "SELECT c.relname FROM pg_class c"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
                        " AND c.relname NOT LIKE 'sm\\_%' AND NOT c.relforcerowsecurity"
                    )
                )
            )
            .scalars()
            .all()
        )
        if unforced:
            problems.append(f"tables without FORCE ROW LEVEL SECURITY: {sorted(unforced)}")
    return problems


async def _functional(db: Database, tables: Sequence[str], other: DbContext) -> list[str]:
    problems: list[str] = []
    for table in tables:
        if not _TABLE_NAME.match(table):
            msg = f"unsafe table name in self-test list: {table!r}"
            raise SelfTestError(msg)
        query = text(f"SELECT count(*) FROM {table}")  # noqa: S608 - name validated above
        async with db.unscoped_for_self_test() as s:
            if (await s.execute(query)).scalar_one() != 0:
                problems.append(f"{table}: query with no context returned rows")
        async with db.scoped(other) as s:
            if (await s.execute(query)).scalar_one() != 0:
                problems.append(f"{table}: query for an unrelated workspace returned rows")
    return problems


async def boot_self_test(db: Database, *, readable_tables: Sequence[str], other: DbContext) -> None:
    """Raise ``SelfTestError`` unless every isolation property holds.

    Args:
        db: The service's own connection.
        readable_tables: Tables this service role may read under RLS (the gateway passes none,
            because ``principal_v`` is its only relation and is readable by design).
        other: A context for a workspace that owns no data (random identifiers).
    """
    problems = await _structural(db)
    problems += await _functional(db, readable_tables, other)
    if problems:
        msg = "isolation self-test failed: " + "; ".join(problems)
        raise SelfTestError(msg)
