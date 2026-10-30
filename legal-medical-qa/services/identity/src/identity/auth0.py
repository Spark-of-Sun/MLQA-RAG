"""The Auth0 Management API adapter (doc 8.8). NOT executed here: it needs real Auth0 credentials.

Only the identity service holds the machine-to-machine credential, with the minimal scopes the
design lists (organizations, members, roles, sessions and refresh tokens). Roles are defined once
per Auth0 tenant and assigned per organization membership; ``app_metadata.privileged`` forces
passkey enrollment at the next sign-in (doc 8.4).
"""

from __future__ import annotations

import time
from typing import Any, Final

import httpx

_TIMEOUT: Final = 15.0


class Auth0Error(RuntimeError):
    """The Management API refused or failed."""


class Auth0Management:
    """A small, explicit client over the Management API v2."""

    def __init__(
        self, domain: str, client_id: str, client_secret: str, audience: str | None = None
    ) -> None:
        """``domain`` is the tenant domain.

        Credentials come from the identity service's own secrets.
        """
        self._base = f"https://{domain}"
        self._creds = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": audience or f"{self._base}/api/v2/",
        }
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        self._token: tuple[str, float] | None = None

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def _headers(self) -> dict[str, str]:
        if self._token is None or self._token[1] < time.monotonic() + 30:
            response = await self._client.post(f"{self._base}/oauth/token", json=self._creds)
            if response.status_code != 200:  # noqa: PLR2004
                msg = f"cannot obtain a Management API token ({response.status_code})"
                raise Auth0Error(msg)
            body = response.json()
            self._token = (str(body["access_token"]), time.monotonic() + float(body["expires_in"]))
        return {"Authorization": f"Bearer {self._token[0]}"}

    async def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        response = await self._client.request(
            method, f"{self._base}/api/v2{path}", headers=await self._headers(), **kwargs
        )
        if response.status_code >= 400:  # noqa: PLR2004
            msg = f"Auth0 {method} {path} failed ({response.status_code})"
            raise Auth0Error(msg)
        return response.json() if response.content else {}

    async def create_organization(self, name: str, display_name: str) -> str:
        """Create an Auth0 Organization and return its ID (one per our organization, doc 8.1)."""
        body = await self._call(
            "POST", "/organizations", json={"name": name, "display_name": display_name}
        )
        return str(body["id"])

    async def add_member(self, org_id: str, user_sub: str) -> None:
        """Add a user to the Organization."""
        await self._call("POST", f"/organizations/{org_id}/members", json={"members": [user_sub]})

    async def assign_role(self, org_id: str, user_sub: str, role_id: str) -> None:
        """Assign a tenant-wide role to a member of this Organization."""
        await self._call(
            "POST", f"/organizations/{org_id}/members/{user_sub}/roles", json={"roles": [role_id]}
        )

    async def mark_privileged(self, user_sub: str) -> None:
        """Set ``app_metadata.privileged``: the next sign-in forces a phishing-resistant factor."""
        await self._call("PATCH", f"/users/{user_sub}", json={"app_metadata": {"privileged": True}})

    async def revoke_access(self, org_id: str, user_sub: str) -> None:
        """Suspension: remove the membership, delete refresh tokens and end sessions (doc 8.6)."""
        await self._call("DELETE", f"/organizations/{org_id}/members", json={"members": [user_sub]})
        await self._call("DELETE", f"/users/{user_sub}/refresh-tokens")
        await self._call("DELETE", f"/users/{user_sub}/sessions")
