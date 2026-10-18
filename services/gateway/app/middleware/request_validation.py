from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse

_MAX_BODY_BYTES = 25 * 1024 * 1024  # 25MB — generous for a scanned-PDF upload request
_PUBLIC_PATHS = {"/healthz", "/docs", "/openapi.json", "/redoc"}


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Cheap, cross-cutting checks before auth/rate-limit do real work:
    rejects oversized or malformed Content-Length up front. Per-field
    validation of the parsed body is handled by pydantic schemas in each
    router (app/schemas) — this middleware is not a substitute for that.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if request.url.path not in _PUBLIC_PATHS:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "invalid Content-Length"})
                if length > _MAX_BODY_BYTES:
                    return JSONResponse(status_code=413, content={"detail": "request body too large"})

        return await call_next(request)
