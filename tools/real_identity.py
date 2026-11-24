"""Real Auth0 identities for `make demo`, `make demo-web` and `make eval` (R-27, R-89; closes DEV-35).

Nothing here signs a token. Each role is a real account in the Auth0 tenant that signed in once through
Universal Login via the auth harness (tools/auth_harness.py), which stores the issued tokens in
`data/auth_harness/<label>.json` (mode 0600). This module reads them, refreshes an expired access token with
the stored refresh token, and hands the access token to the gateway, which verifies it against the tenant's
JWKS exactly as in production. Claims are read here only to label users; the gateway does the verification.

Sign a role in (once; the refresh token keeps it alive):

    uv run python tools/auth_harness.py serve &
    uv run python tools/auth_harness.py url --label demo-alice     # open the URL, sign in as that account
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from auth_harness import STATE_DIR

from lmqa_models.envfile import merged_env

REQUIRED_ENV = (
    "AUTH0_DOMAIN",
    "AUTH0_AUDIENCE_MAIN",
    "AUTH0_CLIENT_ID_HARNESS",
    "AUTH0_CLIENT_SECRET_HARNESS",
)


@dataclass(frozen=True)
class Identity:
    label: str
    token: str
    sub: str
    email: str
    name: str

    @property
    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}


def _claims(token: str) -> dict[str, Any]:
    # Display only: the gateway verifies issuer, audience, signature and expiry against Auth0's JWKS.
    return jwt.decode(token, options={"verify_signature": False})


def _refresh(env: dict[str, str], label: str, stored: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(
        f"https://{env['AUTH0_DOMAIN']}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": env["AUTH0_CLIENT_ID_HARNESS"],
            "client_secret": env["AUTH0_CLIENT_SECRET_HARNESS"],
            "refresh_token": stored["refresh_token"],
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise SystemExit(
            f"Auth0 refused to refresh the '{label}' session (HTTP {resp.status_code}). "
            f"Sign it in again: python tools/auth_harness.py url --label {label}"
        )
    fresh = {**stored, **resp.json()}  # rotation returns a new refresh token; keep it
    fd = os.open(STATE_DIR / f"{label}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(fresh, fh)
    return fresh


def load(labels: list[str], claims_namespace: str) -> dict[str, Identity]:
    """Return a real identity per label, or exit with a message naming what is missing."""
    env = merged_env()
    missing_env = [name for name in REQUIRED_ENV if not env.get(name)]
    missing = [label for label in labels if not (STATE_DIR / f"{label}.json").is_file()]
    if missing_env or missing:
        lines = ["This command uses real Auth0 identities (R-27); no local token signer exists."]
        if missing_env:
            lines.append("Set these environment variables: " + ", ".join(missing_env))
        if missing:
            lines.append(
                "Sign these accounts in once through the auth harness (tools/auth_harness.py): "
                + ", ".join(missing)
            )
            lines.append("  python tools/auth_harness.py serve &")
            lines.append("  python tools/auth_harness.py url --label <label>   # then open the URL")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(2)

    out: dict[str, Identity] = {}
    for label in labels:
        stored = json.loads((STATE_DIR / f"{label}.json").read_text(encoding="utf-8"))
        if _claims(stored["access_token"]).get("exp", 0) - 60 <= time.time():
            if not stored.get("refresh_token"):
                raise SystemExit(
                    f"The '{label}' access token expired and has no refresh token. "
                    f"Sign it in again: python tools/auth_harness.py url --label {label}"
                )
            stored = _refresh(env, label, stored)
        access = _claims(stored["access_token"])
        profile = _claims(stored["id_token"]) if stored.get("id_token") else {}
        out[label] = Identity(
            label=label,
            token=stored["access_token"],
            sub=str(access["sub"]),
            email=str(access.get(f"{claims_namespace}/email") or profile.get("email", "")),
            name=str(access.get(f"{claims_namespace}/name") or profile.get("name", label)),
        )
    return out
