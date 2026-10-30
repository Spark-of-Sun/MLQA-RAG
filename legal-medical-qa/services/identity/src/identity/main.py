"""Identity service entrypoint: ``uvicorn identity.main:app``.

Needs: PG_DSN_IDENTITY, VALKEY_URL, a KMS (KMS_PROVIDER), the trust root, CODE_PEPPER_V1,
and for real
sign-ups the Auth0 Management credentials (AUTH0_M2M_*). Without Auth0 credentials the service still
starts but does not call Auth0 (development only; it logs a warning).
"""

from __future__ import annotations

import logging
from typing import Final

from identity.app import create_app
from identity.auth0 import Auth0Management
from identity.codes import CodeService, RateLimiter
from identity.domain import Identity
from lmqa_auth.runtime import (
    context_verifier,
    database,
    env,
    key_provider,
    optional_env,
    valkey_client,
)
from lmqa_keys import KeyService

LOG: Final = logging.getLogger("identity")


def build() -> Identity:
    """Construct the domain object from the environment."""
    db, valkey, provider = database("IDENTITY"), valkey_client("IDENTITY"), key_provider()
    pepper_id = env("CODE_PEPPER_ID", "v1")
    peppers = {pepper_id: bytes.fromhex(env("CODE_PEPPER_V1"))}
    client_id, client_secret = (
        optional_env("AUTH0_M2M_CLIENT_ID"),
        optional_env("AUTH0_M2M_CLIENT_SECRET"),
    )
    auth0 = None
    if client_id and client_secret:
        auth0 = Auth0Management(env("AUTH0_DOMAIN"), client_id, client_secret)
    else:
        LOG.warning(
            "Auth0 Management credentials are not set: organizations are not mirrored to Auth0"
        )
    production = env("APP_ENV", "local") == "production"
    return Identity(
        db,
        KeyService(provider),
        provider,
        CodeService(db, RateLimiter(valkey), peppers, pepper_id),
        valkey,
        auth0,
        auto_activate_orgs=not production,  # production: an operator approves organizations (D9)
    )


identity = build()
app = create_app(identity, context_verifier("identity", identity.valkey))
