"""The scoped session: the only door to PostgreSQL for services (doc 4.7, 10.3).

``Database.scoped`` opens a transaction, applies the request context with transaction-local
``set_config`` and yields a session. There is no other public way to run a query, so a query
without a context cannot be written by accident.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from lmqa_db.context import DbContext, MissingContextError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine

_SET_CONTEXT = text(
    "SELECT set_config('app.role', :role, true), set_config('app.org_id', :org, true),"
    " set_config('app.workspace_id', :ws, true), set_config('app.user_id', :usr, true)"
)


def to_async_url(dsn: str) -> str:
    """Convert a libpq style DSN into a SQLAlchemy async psycopg URL."""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn.removeprefix(prefix)
    return dsn


class Database:
    """A connection to PostgreSQL for one service role."""

    def __init__(self, dsn: str, *, pooled: bool = True, use_null_pool: bool = False) -> None:
        """Create the engine.

        Args:
            dsn: Connection string for the service's own login role.
            pooled: True when the DSN goes through PgBouncer in transaction mode. Server-side
                prepared statements are then disabled, because they are connection state.
            use_null_pool: Open a fresh connection per transaction (tests, workers).
        """
        connect_args: dict[str, object] = {"prepare_threshold": None} if pooled else {}
        self._engine: AsyncEngine = create_async_engine(
            to_async_url(dsn),
            connect_args=connect_args,
            poolclass=NullPool if use_null_pool else None,
            pool_pre_ping=not use_null_pool,
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @asynccontextmanager
    async def scoped(self, ctx: DbContext | None) -> AsyncGenerator[AsyncSession]:
        """Run one transaction with ``ctx`` applied. Refuses to run without a context."""
        if ctx is None:
            msg = "a database context is required; unscoped queries are not allowed"
            raise MissingContextError(msg)
        ctx.validate()
        settings = ctx.settings()
        async with self._sessions() as session, session.begin():
            await session.execute(
                _SET_CONTEXT,
                {
                    "role": settings["app.role"],
                    "org": settings["app.org_id"],
                    "ws": settings["app.workspace_id"],
                    "usr": settings["app.user_id"],
                },
            )
            yield session

    @asynccontextmanager
    async def unscoped_for_self_test(self) -> AsyncGenerator[AsyncSession]:
        """Open a transaction with NO context. Only the boot self-test may use this."""
        async with self._sessions() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        """Close the connection pool."""
        await self._engine.dispose()
