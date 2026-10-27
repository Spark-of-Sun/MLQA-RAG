"""Gateway service configuration per .env.example."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class GatewayConfig(BaseModel):
    """Runtime configuration for API Gateway service."""

    model_config = ConfigDict(frozen=True)

    auth0_domain: str = Field(
        default_factory=lambda: os.getenv("AUTH0_DOMAIN", "your-tenant.auth0.com")
    )
    audience_main: str = Field(
        default_factory=lambda: os.getenv("AUTH0_AUDIENCE_MAIN", "https://api.lmqa.local/v1")
    )
    audience_onboarding: str = Field(
        default_factory=lambda: os.getenv(
            "AUTH0_AUDIENCE_ONBOARDING", "https://onboard.lmqa.local/v1"
        )
    )
    client_id_bff: str = Field(default_factory=lambda: os.getenv("AUTH0_CLIENT_ID_BFF", ""))
    claims_namespace: str = Field(
        default_factory=lambda: os.getenv("AUTH0_CLAIMS_NAMESPACE", "https://lmqa.local/claims")
    )
    pg_dsn: str = Field(
        default_factory=lambda: os.getenv(
            "PG_DSN_GATEWAY",
            "postgresql+asyncpg://lmqa_gateway:secret@localhost:6432/lmqa",
        )
    )

    def is_auth0_configured(self) -> bool:
        """Check if production Auth0 tenant domain is configured."""
        return bool(self.auth0_domain and not self.auth0_domain.startswith("your-tenant"))
