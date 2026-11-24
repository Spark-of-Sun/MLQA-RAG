"""Auth0 Management API client (blueprint 8.1, 8.6, 8.8, G2.11). Only the identity service holds these credentials.

The M2M application is granted exactly `SCOPES`; `verify_scopes` refuses to run with a token carrying more (least
privilege is checked, not assumed). Tokens are cached until a minute before expiry. Every call has a timeout and
retries only idempotent methods on 429 and 5xx, honoring `Retry-After`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

SCOPES = frozenset(
    {
        "read:organizations",
        "create:organizations",
        "update:organizations",
        "delete:organizations",
        "read:organization_members",
        "create:organization_members",
        "delete:organization_members",
        "read:organization_member_roles",
        "create:organization_member_roles",
        "delete:organization_member_roles",
        "create:organization_connections",
        "read:roles",
        "read:users",
        "update:users",
        "delete:refresh_tokens",
        "delete:sessions",
        "read:users_app_metadata",
        "update:users_app_metadata",
    }
)
_IDEMPOTENT = {"GET", "PUT", "DELETE"}


class Auth0Error(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Auth0Config:
    domain: str
    client_id: str
    client_secret: str
    connection_id: str | None = (
        None  # the database or passkey connection enabled on every organization
    )
    role_ids: tuple[tuple[str, str], ...] = ()  # (our role, Auth0 role id)

    def __repr__(self) -> str:
        return f"Auth0Config(domain={self.domain!r})"


class Auth0Management:
    def __init__(self, config: Auth0Config, *, client: httpx.Client | None = None) -> None:
        self._cfg = config
        self._http = client or httpx.Client(base_url=f"https://{config.domain}", timeout=10.0)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # --- token ----------------------------------------------------------------------------------------------

    def _access_token(self) -> str:
        with self._lock:
            if self._token and self._token[1] > time.time() + 60:
                return self._token[0]
            resp = self._http.post(
                "/oauth/token",
                json={
                    "grant_type": "client_credentials",
                    "client_id": self._cfg.client_id,
                    "client_secret": self._cfg.client_secret,
                    "audience": f"https://{self._cfg.domain}/api/v2/",
                },
            )
            if resp.status_code != 200:
                raise Auth0Error("management token request refused", resp.status_code)
            body = resp.json()
            granted = frozenset(str(body.get("scope", "")).split())
            extra = granted - SCOPES
            if extra:
                raise Auth0Error(
                    f"management token carries scopes beyond the allow-list: {sorted(extra)}"
                )
            self._token = (
                str(body["access_token"]),
                time.time() + int(body.get("expires_in", 600)),
            )
            return self._token[0]

    def verify_scopes(self) -> frozenset[str]:
        self._token = None
        self._access_token()
        return SCOPES

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Any = None,
        ok: tuple[int, ...] = (200, 201, 204),
    ) -> Any:
        for attempt in range(4):
            resp = self._http.request(
                method,
                f"/api/v2{path}",
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {self._access_token()}"},
            )
            if resp.status_code in ok:
                return resp.json() if resp.content else None
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if retryable and (method in _IDEMPOTENT or resp.status_code == 429) and attempt < 3:
                time.sleep(min(float(resp.headers.get("Retry-After", 2**attempt)), 10.0))
                continue
            raise Auth0Error(f"{method} {path.split('?', maxsplit=1)[0]} failed", resp.status_code)
        raise Auth0Error(f"{method} {path} exhausted retries")

    # --- organizations --------------------------------------------------------------------------------------

    def create_organization(self, *, name: str, display_name: str, metadata: dict[str, str]) -> str:
        org = self._call(
            "POST",
            "/organizations",
            json={
                "name": name,
                "display_name": display_name[:255],
                "metadata": metadata,
            },
        )
        org_id = str(org["id"])
        if self._cfg.connection_id:
            self._call(
                "POST",
                f"/organizations/{org_id}/enabled_connections",
                json={
                    "connection_id": self._cfg.connection_id,
                    "assign_membership_on_login": False,
                },
            )
        return org_id

    def find_organization(self, name: str) -> str | None:
        try:
            org = self._call("GET", f"/organizations/name/{quote(name, safe='')}")
        except Auth0Error as exc:
            if exc.status == 404:
                return None
            raise
        return str(org["id"])

    def delete_organization(self, org_id: str) -> None:
        self._call("DELETE", f"/organizations/{org_id}", ok=(200, 204, 404))

    def add_member(self, org_id: str, user_sub: str) -> None:
        self._call("POST", f"/organizations/{org_id}/members", json={"members": [user_sub]})

    def remove_member(self, org_id: str, user_sub: str) -> None:
        self._call(
            "DELETE",
            f"/organizations/{org_id}/members",
            json={"members": [user_sub]},
            ok=(200, 204, 404),
        )

    def role_id(self, role: str) -> str | None:
        return dict(self._cfg.role_ids).get(role)

    def assign_role(self, org_id: str, user_sub: str, role: str) -> None:
        rid = self.role_id(role)
        if rid:
            self._call(
                "POST",
                f"/organizations/{org_id}/members/{quote(user_sub, safe='')}/roles",
                json={"roles": [rid]},
            )

    def member_roles(self, org_id: str, user_sub: str) -> list[str]:
        rows = (
            self._call("GET", f"/organizations/{org_id}/members/{quote(user_sub, safe='')}/roles")
            or []
        )
        by_id = {v: k for k, v in self._cfg.role_ids}
        return sorted(by_id.get(r["id"], r.get("name", r["id"])) for r in rows)

    def members(self, org_id: str) -> list[str]:
        out: list[str] = []
        page = 0
        while True:
            rows = self._call(
                "GET", f"/organizations/{org_id}/members", params={"page": page, "per_page": 100}
            )
            items = rows.get("members", rows) if isinstance(rows, dict) else rows
            out += [str(m["user_id"]) for m in items or []]
            if not items or len(items) < 100:
                return out
            page += 1

    # --- revocation (8.6) -----------------------------------------------------------------------------------

    def revoke_user_sessions(self, user_sub: str) -> None:
        """Delete refresh tokens and sessions: the next refresh fails and SSO cannot silently re-authenticate."""
        sub = quote(user_sub, safe="")
        self._call("DELETE", f"/users/{sub}/refresh-tokens", ok=(200, 202, 204, 404))
        self._call("DELETE", f"/users/{sub}/sessions", ok=(200, 202, 204, 404))

    def set_app_metadata(self, user_sub: str, metadata: dict[str, Any]) -> None:
        self._call("PATCH", f"/users/{quote(user_sub, safe='')}", json={"app_metadata": metadata})


def config_from_env(env: dict[str, str]) -> Auth0Config | None:
    domain = (env.get("AUTH0_DOMAIN") or "").removeprefix("https://").rstrip("/")
    cid, secret = env.get("AUTH0_M2M_CLIENT_ID"), env.get("AUTH0_M2M_CLIENT_SECRET")
    if not (domain and cid and secret):
        return None
    roles = tuple(
        (r, v)
        for r in ("super_admin", "admin", "tenant")
        if (v := env.get(f"AUTH0_ROLE_ID_{r.upper()}"))
    )
    return Auth0Config(domain, cid, secret, env.get("AUTH0_CONNECTION_ID"), roles)
