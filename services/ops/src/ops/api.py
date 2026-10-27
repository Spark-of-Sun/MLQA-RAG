"""Ops service API providing health and readiness probes."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Response, status

from ops.probes import check_all_probes

app = FastAPI(title="LMQA Ops Service", version="0.1.0")


@app.get("/health/live", status_code=status.HTTP_200_OK)
async def health_live() -> dict[str, str]:
    """Fast liveness probe for orchestration."""
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready(response: Response) -> dict[str, Any]:
    """Deep readiness probe verifying critical dependencies."""
    report = await check_all_probes()
    if report.get("status") != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK
    return report


@app.get("/metrics", status_code=status.HTTP_200_OK)
async def metrics() -> dict[str, Any]:
    """Operational metrics endpoint."""
    return {
        "service": "ops",
        "version": "0.1.0",
        "status": "healthy",
    }
