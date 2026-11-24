"""Log redaction (R-16 criterion 10, R-60 criterion 5, design: `lmqa_security` logging redaction).

`install()` wraps the log record factory, so every record from every logger (ours, uvicorn, libraries) is redacted
when it is created, before any handler or formatter sees it. Redaction removes:

- join codes (32- and 64-character Crockford Base32, with or without the display separators);
- bearer tokens and JWTs (access tokens, ID tokens, context tokens);
- e-mail addresses (contact fields);
- the value of any sensitive key written as `key=value`, `key: value` or `"key": "value"` (codes, tokens, titles,
  chunk text, questions, answers, contact fields).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any

MASK = "[REDACTED]"

# Keys whose values are secrets or content. Shared with the audit metadata builder (`lmqa_audit.meta`).
SENSITIVE_KEYS = frozenset(
    {
        # join codes
        "code",
        "join_code",
        "invite_code",
        "org_code",
        "admin_code",
        "organization_code",
        # tokens and credentials
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "context_token",
        "x_context_token",
        "bearer",
        "jwt",
        "authorization",
        "cookie",
        "set_cookie",
        "password",
        "secret",
        "client_secret",
        "api_key",
        "pepper",
        # content
        "title",
        "name",
        "text",
        "chunk_text",
        "content",
        "body",
        "question",
        "answer",
        "prompt",
        "query",
        "message",
        "note",
        "detail_note",
        "comment",
        "description",
        "snippet",
        "excerpt",
        "segment",
        # contact fields
        "email",
        "phone",
        "contact",
        "address",
        "display_name",
        "full_name",
        "first_name",
        "last_name",
    }
)

SENSITIVE_SUFFIXES = (
    "_token",
    "_code",
    "_secret",
    "_password",
    "_email",
    "_phone",
    "_name",
    "_title",
    "_text",
    "_note",
)

_C = "[0-9A-HJKMNP-TV-Z]"  # Crockford Base32, upper case
_CODE = re.compile(
    rf"(?<![0-9A-Za-z]){_C}{{8}}(?:[- ]?{_C}{{8}}){{3}}(?:(?:[- ]?{_C}{{8}}){{4}})?(?![0-9A-Za-z])"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_KEYS = "|".join(sorted((re.escape(k) for k in SENSITIVE_KEYS), key=len, reverse=True))
_PAIR = re.compile(
    rf"""(?ix)
    (?<![A-Za-z0-9_])(["']?(?:{_KEYS})["']?)   # key, optionally quoted
    (\s*[:=]\s*)                                # separator
    ("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,;&}}\]\)]+)   # value: quoted string or bare word
    """
)


def is_sensitive_key(key: str) -> bool:
    k = key.lower().replace("-", "_")
    return k in SENSITIVE_KEYS or k.endswith(SENSITIVE_SUFFIXES)


def redact_text(text: str) -> str:
    """Remove codes, tokens, e-mail addresses and sensitive key values from free text."""
    text = _JWT.sub(MASK, text)
    text = _BEARER.sub(rf"\1 {MASK}", text)
    text = _PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    text = _CODE.sub(MASK, text)
    return _EMAIL.sub(MASK, text)


def redact_value(value: Any, key: str | None = None) -> Any:
    """Redact a structured value: sensitive keys are masked whole, strings are scrubbed, containers recurse."""
    if key is not None and is_sensitive_key(key) and value is not None:
        return MASK
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        items: Mapping[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
        return {k: redact_value(v, str(k)) for k, v in items.items()}
    if isinstance(value, list | tuple):
        seq: list[Any] | tuple[Any, ...] = value  # pyright: ignore[reportUnknownVariableType]
        return [redact_value(v) for v in seq]
    return value


_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}


def redact(record: logging.LogRecord) -> logging.LogRecord:
    """Redact one record in place and return it: message, arguments, exception text and `extra` fields."""
    try:
        message = record.getMessage()
    except Exception:  # a bad format string must not lose the record
        message = f"{record.msg!s} {record.args!r}"
    record.msg, record.args = redact_text(message), None
    if record.exc_info and not record.exc_text:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = redact_text(record.exc_text)
        record.exc_info = None
    if record.stack_info:
        record.stack_info = redact_text(record.stack_info)
    for key in set(record.__dict__) - _STANDARD:
        record.__dict__[key] = redact_value(record.__dict__[key], key)
    return record


def install() -> None:
    """Redact every log record at creation. Idempotent."""
    previous: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()
    if getattr(previous, "_lmqa_redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        return redact(previous(*args, **kwargs))

    factory._lmqa_redacting = True  # type: ignore[attr-defined] # pyright: ignore[reportFunctionMemberAccess]
    logging.setLogRecordFactory(factory)


def configure_logging(level: int | str = logging.INFO, fmt: str | None = None) -> None:
    """The shared logging setup for every service entry point: basic configuration plus redaction."""
    install()
    if fmt is None:
        logging.basicConfig(level=level)
    else:
        logging.basicConfig(level=level, format=fmt)
