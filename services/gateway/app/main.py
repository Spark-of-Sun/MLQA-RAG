from __future__ import annotations

import os
from contextlib import asynccontextmanager

from common.logging import configure_logging, get_logger
from common.telemetry import configure_tracing
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.middleware.auth_middleware import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_validation import RequestValidationMiddleware
from app.routers import admin, audit, documents, query
from app.state import AppState

configure_logging(service_name="gateway")
configure_tracing(service_name="gateway")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.legalmed = await AppState.create()
    log.info("gateway_startup", environment=os.environ.get("ENVIRONMENT", "local"))
    yield
    await app.state.legalmed.aclose()
    log.info("gateway_shutdown")


app = FastAPI(
    title="Legal/Medical QA — Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware executes in the REVERSE order it's added (last added runs
# first). We want: validate -> auth -> rate-limit (rate limit needs the
# tenant/user that auth just verified), so RateLimit is added first
# (innermost/last-to-run) and RequestValidation last (outermost/first-to-run).
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestValidationMiddleware)

app.include_router(query.router, prefix="/v1")
app.include_router(documents.router, prefix="/v1")
app.include_router(audit.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1/admin")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


if os.environ.get("ENVIRONMENT", "local") == "local":
    # Local-dev convenience only: mints a session JWT without needing the
    # Next.js/NextAuth frontend running yet. Never mounted outside local mode.
    from app.auth.idp import dev_router

    app.include_router(dev_router, prefix="/v1/dev")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
