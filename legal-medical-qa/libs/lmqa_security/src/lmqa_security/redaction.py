"""Log redaction (doc 7.6, 23): codes, tokens and secrets never reach a log line.

Used as a structlog processor and for ad hoc scrubbing. Keys are matched case-insensitively
by substring, so ``admin_code``, ``Authorization`` and ``x-api-key`` are all caught.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final, cast

REDACTED: Final = "[REDACTED]"
SENSITIVE_KEYS: Final = (
    "code",
    "token",
    "secret",
    "password",
    "pepper",
    "authorization",
    "cookie",
    "api_key",
    "api-key",
    "apikey",
    "private_key",
    "session",
)
_CROCKFORD_RUN: Final = re.compile(
    r"\b[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{8,}(?:[- ][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{8}){2,}\b"
)
# A code pasted without dashes: 24 or more contiguous Crockford characters (an Admin Code is 32).
_CONTIGUOUS: Final = re.compile(r"\b[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{24,}\b")
_BEARER: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT: Final = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")


def is_sensitive_key(key: str) -> bool:
    """True if a field name suggests it holds a secret."""
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def scrub_text(text: str) -> str:
    """Remove code-shaped runs, bearer tokens and JWTs from free text."""
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _CROCKFORD_RUN.sub(REDACTED, text)
    return _CONTIGUOUS.sub(REDACTED, text)


def redact(value: object) -> object:
    """Return a copy of ``value`` with sensitive fields and secret-shaped strings removed."""
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {
            k: REDACTED if isinstance(k, str) and is_sensitive_key(k) else redact(v)
            for k, v in mapping.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in cast("tuple[object, ...]", value))
    if isinstance(value, set | frozenset):
        return {redact(v) for v in cast("set[object]", value)}
    if isinstance(value, str):
        return scrub_text(value)
    return value


def structlog_processor(
    _logger: object, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Redact every event before structlog renders it."""
    return cast("dict[str, Any]", redact(event_dict))
