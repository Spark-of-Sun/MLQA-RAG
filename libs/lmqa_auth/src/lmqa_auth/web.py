"""FastAPI helpers shared by every service (doc 15.1).

Errors use ``application/problem+json`` (RFC 9457) with the same body for every security-sensitive
failure, so a response never reveals why a token or an ID was refused. A resource outside the
caller's scope is 404, never 403.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from fastapi import HTTPException, Request, WebSocket, WebSocketException
from fastapi.responses import JSONResponse

from lmqa_auth.context import ContextClaims, ContextTokenError, ContextVerifier

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

PROBLEM: Final = "application/problem+json"
UNAUTHENTICATED: Final = {"type": "about:blank", "title": "Unauthorized", "status": 401}
NOT_FOUND: Final = {"type": "about:blank", "title": "Not Found", "status": 404}


def problem(status: int, title: str, **extra: Any) -> JSONResponse:  # noqa: ANN401
    """A problem+json response."""
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, **extra},
        status_code=status,
        media_type=PROBLEM,
    )


class Unauthorized(HTTPException):
    """The uniform 401: identical for a missing, malformed, expired or wrongly addressed token."""

    def __init__(self) -> None:
        """Always the same body."""
        super().__init__(
            status_code=401, detail=UNAUTHENTICATED["title"], headers={"WWW-Authenticate": "Bearer"}
        )


def ws_context_claims() -> Callable[[WebSocket], Awaitable[ContextClaims]]:
    """WebSocket twin of ``context_claims``: refuse the handshake (1008) on any failure."""

    async def dependency(websocket: WebSocket) -> ContextClaims:
        scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise WebSocketException(code=1008)
        verifier: ContextVerifier = websocket.app.state.verifier
        try:
            return await verifier.verify(token)
        except ContextTokenError as exc:
            raise WebSocketException(code=1008) from exc

    return dependency


def context_claims(
    *, state_changing: bool = False
) -> Callable[[Request], Awaitable[ContextClaims]]:
    """A FastAPI dependency that verifies the Gateway's context token for THIS service.

    The verifier is read from ``app.state.verifier`` (built at startup with this service's own
    audience), so a token minted for another service is rejected here.
    """

    async def dependency(request: Request) -> ContextClaims:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized
        verifier: ContextVerifier = request.app.state.verifier
        try:
            return await verifier.verify(token, state_changing=state_changing)
        except ContextTokenError as exc:
            raise Unauthorized from exc

    return dependency
