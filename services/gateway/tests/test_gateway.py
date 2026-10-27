"""Tests for gateway service configuration."""

from __future__ import annotations

import pytest
from gateway.config import GatewayConfig


@pytest.mark.stage0
@pytest.mark.unit
def test_gateway_config_defaults() -> None:
    """Verify default gateway configuration reflects .env.example specifications."""
    cfg = GatewayConfig()
    assert "auth0.com" in cfg.auth0_domain
    assert "https://api.lmqa.local/v1" in cfg.audience_main
    assert "lmqa_gateway" in cfg.pg_dsn
