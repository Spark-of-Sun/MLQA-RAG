"""Database configuration and async engine connection pool."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection and pooling configuration."""

    host: str = "localhost"
    port: int = 6432
    database: str = "lmqa"
    user: str = "lmqa_admin"
    password: str = ""
    service_dsns: dict[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """Load database configuration from environment variables."""
        services = [
            "gateway",
            "identity",
            "ingestion",
            "retrieval",
            "generation",
            "validator",
            "audit",
            "ops",
        ]
        dsns: dict[str, str] = {}
        for s in services:
            key = f"PG_DSN_{s.upper()}"
            if val := os.environ.get(key):
                dsns[s] = val
            else:
                dsns[s] = f"postgresql+asyncpg://lmqa_{s}:secret@localhost:6432/lmqa"

        return cls(
            host=os.environ.get("PG_HOST", "localhost"),
            port=int(os.environ.get("PG_PORT", "6432")),
            database=os.environ.get("PG_DATABASE", "lmqa"),
            user=os.environ.get("PG_USER", "lmqa_admin"),
            password=os.environ.get("PG_PASSWORD", ""),
            service_dsns=dsns,
        )

    def get_service_dsn(self, service_name: str) -> str:
        """Resolve service-scoped DSN or fallback to default asyncpg connection string."""
        if dsn := self.service_dsns.get(service_name.lower()):
            return dsn
        auth = f"{self.user}:{self.password}@" if self.password else f"{self.user}@"
        return f"postgresql+asyncpg://{auth}{self.host}:{self.port}/{self.database}"

    def get_asyncpg_dsn(self, service_name: str) -> str:
        """Resolve DSN stripped of SQLAlchemy driver prefix for raw asyncpg connections."""
        dsn = self.get_service_dsn(service_name)
        return dsn.replace("postgresql+asyncpg://", "postgresql://")

    def get_admin_dsn(self) -> str:
        """Return admin asyncpg DSN for migrations and administration."""
        auth = f"{self.user}:{self.password}@" if self.password else f"{self.user}@"
        return f"postgresql+asyncpg://{auth}{self.host}:{self.port}/{self.database}"


def create_engine_pool(dsn: str, pool_size: int = 10, max_overflow: int = 5) -> AsyncEngine:
    """Create a SQLAlchemy AsyncEngine for PgBouncer transaction pooling."""
    return create_async_engine(
        dsn,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
    )
