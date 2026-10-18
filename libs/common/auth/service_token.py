from __future__ import annotations

import hmac
import os


class ServiceAuthError(Exception):
    pass


def verify_internal_service_key(provided_key: str | None) -> None:
    """Local-mode service-to-service auth: a shared key via INTERNAL_SERVICE_API_KEY,
    checked with a constant-time comparison. Raises ServiceAuthError on mismatch.

    Production swap (one line, per docs/architecture.md §3): replace this
    check with mTLS client-cert verification or signed per-request service
    tokens at the ASGI middleware layer — callers of this function don't
    need to change.
    """
    expected = os.environ.get("INTERNAL_SERVICE_API_KEY")
    if not expected:
        raise ServiceAuthError("INTERNAL_SERVICE_API_KEY is not set")
    if not provided_key or not hmac.compare_digest(provided_key, expected):
        raise ServiceAuthError("invalid or missing X-Internal-Service-Key")
