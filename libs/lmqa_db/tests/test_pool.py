"""Unit tests for lmqa_db connection configuration and pooling without mocks."""

from __future__ import annotations

import os

import pytest
from lmqa_db import DatabaseConfig, create_engine_pool


@pytest.mark.stage0
@pytest.mark.unit
def test_database_config_defaults() -> None:
    """Test default database parameters when env is unset."""
    cfg = DatabaseConfig()
    assert cfg.host == "localhost"
    assert cfg.port == 6432
    assert cfg.database == "lmqa"
    assert cfg.user == "lmqa_admin"
    assert "postgresql+asyncpg://" in cfg.get_admin_dsn()


@pytest.mark.stage0
@pytest.mark.unit
def test_database_config_from_env() -> None:
    """Test loading database configuration and service DSNs from environment."""
    os.environ["PG_HOST"] = "127.0.0.1"
    os.environ["PG_PORT"] = "5432"
    os.environ["PG_DSN_OPS"] = "postgresql+asyncpg://ops_user:secret@127.0.0.1:5432/lmqa"

    try:
        cfg = DatabaseConfig.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 5432
        assert (
            cfg.get_service_dsn("ops") == "postgresql+asyncpg://ops_user:secret@127.0.0.1:5432/lmqa"
        )
        # Fallback for unconfigured service
        assert "postgresql+asyncpg://" in cfg.get_service_dsn("retrieval")
    finally:
        os.environ.pop("PG_HOST", None)
        os.environ.pop("PG_PORT", None)
        os.environ.pop("PG_DSN_OPS", None)


@pytest.mark.stage0
@pytest.mark.unit
def test_create_engine_pool() -> None:
    """Test creating an async engine pool with configured parameters."""
    dsn = "postgresql+asyncpg://test_user:test_pass@localhost:6432/test_db"
    engine = create_engine_pool(dsn, pool_size=5, max_overflow=2)
    assert engine is not None
    assert engine.url.database == "test_db"
