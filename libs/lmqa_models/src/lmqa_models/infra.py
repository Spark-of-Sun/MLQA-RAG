"""Endpoints and credentials of the local infrastructure (blueprint 4.5, Appendix C).

Names follow Appendix C: `PGBOUNCER_*`, `VALKEY_URL` and `VALKEY_USER_<SERVICE>` (the password of that service's ACL
user), `QDRANT_URL`, `QDRANT_KEY_RO`, `QDRANT_KEY_RW`, `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_CREDS_<ROLE>`
(`access-key:secret-key`), `KMS_PROVIDER`, `OPENBAO_ADDR`, `OPENBAO_TOKEN`. Values are never printed: `__repr__`
names endpoints only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lmqa_models.envfile import is_placeholder, merged_env

# Valkey ACL users, one per caller (blueprint 4.2 "Valkey ACL user"). `test` exists for the infrastructure suite.
VALKEY_USERS = ("gateway", "identity", "retrieval", "generation", "frontend", "doctor", "test")
OBJECT_STORE_ROLES = ("admin", "ingestion")
OBJECT_STORE_BUCKET = "lmqa-objects"


class InfraConfigError(RuntimeError):
    """A required infrastructure setting is missing. The message names the setting, never its value."""


@dataclass(frozen=True)
class InfraSettings:
    pgbouncer_host: str = "127.0.0.1"
    pgbouncer_port: int = 6432
    valkey_url: str = "redis://127.0.0.1:6380/0"
    valkey_passwords: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_key_ro: str | None = field(default=None, repr=False)
    qdrant_key_rw: str | None = field(default=None, repr=False)
    object_store_endpoint: str = "http://127.0.0.1:8333"
    object_store_region: str = "us-east-1"
    object_store_creds: tuple[tuple[str, tuple[str, str]], ...] = field(default=(), repr=False)
    kms_provider: str = "openbao"
    openbao_addr: str = "http://127.0.0.1:8200"
    openbao_token: str | None = field(default=None, repr=False)
    clamav_host: str = "127.0.0.1"
    clamav_port: int = 3310

    def valkey_password(self, user: str) -> str:
        value = dict(self.valkey_passwords).get(user)
        if not value:
            raise InfraConfigError(f"VALKEY_USER_{user.upper()} is not set. Run: make setup")
        return value

    def object_store_credentials(self, role: str) -> tuple[str, str]:
        value = dict(self.object_store_creds).get(role)
        if not value:
            raise InfraConfigError(f"OBJECT_STORE_CREDS_{role.upper()} is not set. Run: make setup")
        return value

    def require(self, name: str) -> str:
        """A secret attribute by setting name, or a clear error naming the missing setting."""
        value = {
            "QDRANT_KEY_RO": self.qdrant_key_ro,
            "QDRANT_KEY_RW": self.qdrant_key_rw,
            "OPENBAO_TOKEN": self.openbao_token,
        }[name]
        if not value:
            raise InfraConfigError(f"{name} is not set. Run: make setup")
        return value


def _value(env: dict[str, str], key: str) -> str | None:
    value = env.get(key)
    return None if is_placeholder(value) else value


def _creds(raw: str | None) -> tuple[str, str] | None:
    if not raw or ":" not in raw:
        return None
    access, _, secret = raw.partition(":")
    return (access, secret) if access and secret else None


def load_infra_settings(env: dict[str, str] | None = None) -> InfraSettings:
    env = merged_env() if env is None else env
    passwords = tuple(
        (u, v) for u in VALKEY_USERS if (v := _value(env, f"VALKEY_USER_{u.upper()}"))
    )
    creds = tuple(
        (r, c)
        for r in OBJECT_STORE_ROLES
        if (c := _creds(_value(env, f"OBJECT_STORE_CREDS_{r.upper()}")))
    )
    return InfraSettings(
        pgbouncer_host=env.get("PGBOUNCER_HOST", "127.0.0.1"),
        pgbouncer_port=int(env.get("PGBOUNCER_PORT", "6432")),
        valkey_url=env.get("VALKEY_URL", f"redis://127.0.0.1:{env.get('VALKEY_PORT', '6380')}/0"),
        valkey_passwords=passwords,
        qdrant_url=env.get("QDRANT_URL", f"http://127.0.0.1:{env.get('QDRANT_PORT', '6333')}"),
        qdrant_key_ro=_value(env, "QDRANT_KEY_RO"),
        qdrant_key_rw=_value(env, "QDRANT_KEY_RW"),
        object_store_endpoint=env.get(
            "OBJECT_STORE_ENDPOINT", f"http://127.0.0.1:{env.get('OBJECT_STORE_PORT', '8333')}"
        ),
        object_store_region=env.get("OBJECT_STORE_REGION", "us-east-1"),
        object_store_creds=creds,
        kms_provider=env.get("KMS_PROVIDER", "openbao"),
        openbao_addr=env.get("OPENBAO_ADDR", f"http://127.0.0.1:{env.get('OPENBAO_PORT', '8200')}"),
        openbao_token=_value(env, "OPENBAO_TOKEN"),
        clamav_host=env.get("CLAMAV_HOST", "127.0.0.1"),
        clamav_port=int(env.get("CLAMAV_PORT", "3310")),
    )
