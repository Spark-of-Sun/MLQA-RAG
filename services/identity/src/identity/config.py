"""Identity service configuration per .env.example."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class IdentityConfig(BaseModel):
    """Runtime configuration for Identity & Tenant Management service."""

    model_config = ConfigDict(frozen=True)

    auth0_domain: str = Field(
        default_factory=lambda: os.getenv("AUTH0_DOMAIN", "your-tenant.auth0.com")
    )
    audience_onboarding: str = Field(
        default_factory=lambda: os.getenv(
            "AUTH0_AUDIENCE_ONBOARDING", "https://onboard.lmqa.local/v1"
        )
    )
    m2m_client_id: str = Field(default_factory=lambda: os.getenv("AUTH0_M2M_CLIENT_ID", ""))
    m2m_client_secret: str = Field(default_factory=lambda: os.getenv("AUTH0_M2M_CLIENT_SECRET", ""))
    pg_dsn: str = Field(
        default_factory=lambda: os.getenv(
            "PG_DSN_IDENTITY",
            "postgresql+asyncpg://lmqa_identity:secret@localhost:6432/lmqa",
        )
    )

    def is_configured(self) -> bool:
        """Check if production Auth0 domain and M2M client credentials are set."""
        return bool(
            self.auth0_domain
            and not self.auth0_domain.startswith("your-tenant")
            and self.m2m_client_id
        )
