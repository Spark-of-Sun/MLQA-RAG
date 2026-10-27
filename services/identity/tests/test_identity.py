"""Tests for identity service configuration."""

from __future__ import annotations

import pytest
from identity.config import IdentityConfig


@pytest.mark.stage0
@pytest.mark.unit
def test_identity_config_defaults() -> None:
    """Verify default identity configuration reflects .env.example specifications."""
    cfg = IdentityConfig()
    assert "auth0.com" in cfg.auth0_domain
    assert "https://onboard.lmqa.local/v1" in cfg.audience_onboarding
    assert "lmqa_identity" in cfg.pg_dsn
