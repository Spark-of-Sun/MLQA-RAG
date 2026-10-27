"""Unit and integration tests for services/ops without mocks."""

from __future__ import annotations

import httpx
import pytest
from ops.api import app
from ops.probes import check_database, check_storage


@pytest.mark.stage0
@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_health_live() -> None:
    """Test fast liveness endpoint."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/health/live")
        assert res.status_code == 200
        assert res.json() == {"status": "live"}


@pytest.mark.stage0
@pytest.mark.unit
@pytest.mark.asyncio
async def test_ops_health_ready_structure() -> None:
    """Test deep readiness endpoint reports structured component status."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/health/ready")
        data = res.json()
        assert "status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert "storage" in data["components"]


@pytest.mark.stage0
@pytest.mark.unit
def test_storage_probe() -> None:
    """Test storage probe execution."""
    ok, msg = check_storage()
    assert ok is True
    assert "Storage" in msg


@pytest.mark.stage0
@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_probe_live() -> None:
    """Test database probe against running local PostgreSQL/PgBouncer."""
    ok, msg = await check_database()
    assert ok is True
    assert "healthy" in msg
