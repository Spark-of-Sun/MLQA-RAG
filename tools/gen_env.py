"""Generate strong random LOCAL secrets into `.env`, the only settings file.

Only settings missing from `.env` and the shell (or still placeholders) are generated; a value that is already set is
never overwritten. `.env` stays mode 600. The database passwords are baked into the Docker volume: keep them while the
volume exists, or run `make db-reset` (deletes local data) to start over. Values are never printed.
"""

from __future__ import annotations

import secrets
import sys

from lmqa_models.envfile import ENV_FILE, fill_missing, is_placeholder, merged_env
from lmqa_models.infra import OBJECT_STORE_ROLES, VALKEY_USERS
from lmqa_models.settings import DB_SERVICE_ROLES


def _s3_credentials() -> str:
    """`access-key:secret-key` in the shape S3 clients expect (20 and 40 characters)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    access = "LMQA" + "".join(secrets.choice(alphabet) for _ in range(16))
    return f"{access}:{secrets.token_urlsafe(30)[:40]}"


GENERATORS = {
    "LMQA_DB_SUPERUSER_PASSWORD": lambda: secrets.token_urlsafe(24),
    "LMQA_DB_OWNER_PASSWORD": lambda: secrets.token_urlsafe(24),
    "LMQA_DB_APP_PASSWORD": lambda: secrets.token_urlsafe(24),
    "CODE_PEPPER_V1": lambda: secrets.token_hex(32),
    "AUTH0_SESSION_SECRET": lambda: secrets.token_hex(32),
    **{
        f"LMQA_DB_{role.upper()}_PASSWORD": (lambda: secrets.token_urlsafe(24))
        for role in DB_SERVICE_ROLES
    },
    # Local infrastructure (compose.yaml, Appendix C names); rendered into data/infra/ by tools/infra_config.py.
    "QDRANT_KEY_RW": lambda: secrets.token_urlsafe(32),
    "QDRANT_KEY_RO": lambda: secrets.token_urlsafe(32),
    "OPENBAO_TOKEN": lambda: "lmqa-dev-" + secrets.token_urlsafe(24),
    # 32-byte static seal key (hex) for OpenBao in local key mode; losing it makes the openbao volume unreadable.
    "OPENBAO_UNSEAL_KEY": lambda: secrets.token_hex(32),
    **{f"OBJECT_STORE_CREDS_{role.upper()}": _s3_credentials for role in OBJECT_STORE_ROLES},
    **{f"VALKEY_USER_{user.upper()}": (lambda: secrets.token_urlsafe(24)) for user in VALKEY_USERS},
}


def main() -> int:
    effective = merged_env()
    missing = [k for k in GENERATORS if is_placeholder(effective.get(k))]
    added = fill_missing(ENV_FILE, {k: GENERATORS[k]() for k in missing})
    if added:
        print(f"generated local secrets into {ENV_FILE.name}: {', '.join(added)}")
    else:
        print("local secrets: already present")
    if is_placeholder(effective.get("AUTH0_DOMAIN")):
        print(
            "note: put your Auth0 and Gemini values in .env (`make doctor` lists what is missing)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
