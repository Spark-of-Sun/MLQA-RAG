"""Internal service endpoints (blueprint 9.1, 9.2, G3.3): what every service runs in front of its handlers once
the services are split into their own deployables (MVP deviation 1, closed at Stage 3).

Two checks on every call:
  1 the caller's service credential (`X-Service-Credential`: a per-service secret locally, mTLS in production),
    so the network layer knows which service is calling;
  2 the context token (`X-Context-Token`), one audience, 60 s, minted by the gateway, which says on whose behalf.
The handler receives the verified `ContextClaims` and builds its database context from them only.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from typing import Annotated

from fastapi import Header, HTTPException, Request

from lmqa_auth.context import ContextClaims, ContextTokenError, ContextVerifier

STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def context_dependency(
    verifier: ContextVerifier,
    credentials: Mapping[str, str],
    allowed_callers: frozenset[str] = frozenset({"gateway"}),
) -> Callable[..., ContextClaims]:
    """`credentials`: caller service name -> its expected secret (constant-time compared)."""

    def dependency(
        request: Request,
        x_context_token: Annotated[str | None, Header()] = None,
        x_service_name: Annotated[str | None, Header()] = None,
        x_service_credential: Annotated[str | None, Header()] = None,
    ) -> ContextClaims:
        expected = credentials.get(x_service_name or "")
        if (
            x_service_name not in allowed_callers
            or not expected
            or not x_service_credential
            or not hmac.compare_digest(expected, x_service_credential)
        ):
            raise HTTPException(401, "invalid context token")
        if not x_context_token:
            raise HTTPException(401, "invalid context token")
        try:
            return verifier.verify(x_context_token, state_changing=request.method in STATE_CHANGING)
        except ContextTokenError:
            raise HTTPException(401, "invalid context token") from None

    return dependency
