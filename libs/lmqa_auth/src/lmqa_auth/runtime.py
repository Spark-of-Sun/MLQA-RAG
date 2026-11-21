"""Build real components from environment variables (doc Appendix C, 9.2).

Every service starts from here: one login role per service, one trust bundle, one Valkey ACL user.
A value that is missing, or still a ``<PLACEHOLDER>`` from ``.env.example``, stops the service with
a clear message instead of starting half configured (fail closed).
"""

from __future__ import annotations

import os
from typing import Final

from valkey.asyncio import Valkey

from lmqa_auth.context import ContextVerifier
from lmqa_auth.stores import ValkeyDenyList, ValkeyJtiStore
from lmqa_db import Database
from lmqa_keys import (
    AwsKmsProvider,
    AwsKmsTrustRoot,
    KeyProvider,
    OpenBaoProvider,
    OpenBaoTrustRoot,
    TrustRoot,
)
from lmqa_keys.aws_kms import kms_key_policy

DEFAULT_TRUST_ROOT_NAME: Final = "lmqa-trust-root"


class ConfigError(RuntimeError):
    """A required setting is missing or still a placeholder."""


def env(name: str, default: str | None = None) -> str:
    """Read a setting; refuse an unset value and an unreplaced ``<PLACEHOLDER>``."""
    value = os.environ.get(name, default)
    if value is None or value == "":
        msg = f"{name} is not set (see .env.example)"
        raise ConfigError(msg)
    if value.startswith("<") and value.endswith(">"):
        msg = f"{name} still holds the placeholder {value}; set a real value"
        raise ConfigError(msg)
    return value


def optional_env(name: str) -> str | None:
    """A setting that may legitimately be absent (a placeholder counts as absent)."""
    value = os.environ.get(name)
    if not value or (value.startswith("<") and value.endswith(">")):
        return None
    return value


def database(service: str, *, pooled: bool = True) -> Database:
    """The service's own login role, through PgBouncer unless ``pooled`` is false (workers)."""
    return Database(env(f"PG_DSN_{service.upper()}"), pooled=pooled)


def valkey_client(service: str) -> Valkey:
    """A Valkey client; uses the service's ACL user when one is configured."""
    user, password = (
        optional_env(f"VALKEY_USER_{service.upper()}"),
        optional_env(f"VALKEY_PASSWORD_{service.upper()}"),
    )
    url = env("VALKEY_URL", "redis://localhost:6379")
    if user and password:
        return Valkey.from_url(url, username=user, password=password)
    return Valkey.from_url(url)


def key_provider() -> KeyProvider:
    """AWS KMS in production, OpenBao Transit locally (doc 12.10). No fake provider exists."""
    kind = env("KMS_PROVIDER", "aws")
    if kind == "aws":
        destroyer, admin = (
            optional_env("KEYGUARD_APPROVER_ROLE_ARN"),
            optional_env("KEYGUARD_ADMIN_ROLE_ARN"),
        )
        policy = (
            kms_key_policy(env("AWS_ACCOUNT_ID"), destroyer, admin) if destroyer and admin else None
        )
        if policy is None and env("APP_ENV", "local") == "production":
            msg = (
                "production keys must carry the KeyGuard policy: "
                "set KEYGUARD_APPROVER_ROLE_ARN and KEYGUARD_ADMIN_ROLE_ARN"
            )
            raise ConfigError(msg)
        return AwsKmsProvider(env("AWS_REGION", "us-east-1"), key_policy=policy)
    if kind == "openbao":
        return OpenBaoProvider(env("OPENBAO_ADDR"), env("OPENBAO_TOKEN"))
    msg = f"unknown KMS_PROVIDER {kind!r}"
    raise ConfigError(msg)


def trust_root() -> TrustRoot:
    """The key that certifies signer keys. Only the Gateway and the validator sign with it."""
    if env("KMS_PROVIDER", "aws") == "aws":
        return AwsKmsTrustRoot(env("AWS_REGION", "us-east-1"), env("KMS_TRUST_ROOT_ID"))
    return OpenBaoTrustRoot(
        env("OPENBAO_ADDR"),
        env("OPENBAO_TOKEN"),
        env("OPENBAO_TRUST_ROOT_KEY", DEFAULT_TRUST_ROOT_NAME),
    )


def trust_bundle() -> list[bytes]:
    """The trusted verification keys, fetched synchronously at start-up (rotation overlap: two)."""
    root = trust_root()
    if isinstance(root, (AwsKmsTrustRoot, OpenBaoTrustRoot)):
        return [root.public_key_pem_sync()]
    msg = "unsupported trust root"
    raise ConfigError(msg)


def context_verifier(service: str, valkey: Valkey) -> ContextVerifier:
    """Verify Gateway context tokens addressed to ``service`` (and nobody else's)."""
    return ContextVerifier(
        trust_bundle(),
        service=service,
        deny_list=ValkeyDenyList(valkey),
        jti_store=ValkeyJtiStore(valkey),
    )
