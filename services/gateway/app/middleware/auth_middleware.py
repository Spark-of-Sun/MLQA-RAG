from __future__ import annotations

from common.auth.jwt import JWTError, decode_session_jwt
from common.logging import get_logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

log = get_logger(__name__)

_PUBLIC_PATHS = {"/healthz", "/docs", "/openapi.json", "/redoc"}
_PUBLIC_PREFIXES = ("/v1/dev",)  # local-only session-minting convenience; never mounted outside local mode


class AuthMiddleware(BaseHTTPMiddleware):
    """Verifies the session JWT the Next.js BFF attaches to every request
    and stores the decoded claims on request.state.claims. Routers read
    request.state.claims rather than re-verifying the token themselves.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(status_code=401, content={"detail": "missing bearer token"})

        token = auth_header.split(" ", 1)[1]
        try:
            claims = decode_session_jwt(token)
        except JWTError as exc:
            log.warning("auth_rejected", path=path, error=str(exc))
            return JSONResponse(status_code=401, content={"detail": "invalid or expired session"})

        request.state.claims = claims
        return await call_next(request)
