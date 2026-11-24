"""Audit event metadata builder (R-60 criteria 1 and 5). Metadata holds typed, enumerated or ID fields only; free
text (titles, questions, answers, chunk text, contact fields, reasons typed by people) belongs in the sealed payload
(`lmqa_audit.append(..., content=...)`) or nowhere. Construction rejects anything else with `FreeTextError`.

Accepted values: None, bool, int, float, UUID, date and datetime (stored as ISO 8601), Enum members, and strings
that are a UUID, a hex digest, or one whitespace-free token (enumerated codes such as `expired`, model names, lookup
IDs, ticket references, ISO timestamps). Lists and nested mappings of those are accepted. Keys must be snake_case
and must not name a secret or content field (`lmqa_security.redact.is_sensitive_key`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any

from lmqa_security.redact import is_sensitive_key

_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")
_MAX_ITEMS = 1000
_MAX_DEPTH = 4


class FreeTextError(ValueError):
    """An audit metadata field is free text or names a content or secret field."""


def check_token(value: str, what: str) -> str:
    if not _TOKEN.fullmatch(value):
        raise FreeTextError(f"{what} must be a single token, got free text")
    return value


def _clean(key: str, value: Any, depth: int) -> Any:  # noqa: PLR0911 - one branch per accepted type
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Enum):
        return _clean(key, value.value, depth)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        return check_token(value, f"audit metadata field {key!r}")
    if depth >= _MAX_DEPTH:
        raise FreeTextError(f"audit metadata field {key!r} is nested too deeply")
    if isinstance(value, Mapping):
        items: Mapping[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
        return _fields(items, depth + 1)
    if isinstance(value, list | tuple | set | frozenset):
        seq: list[Any] = list(value)  # pyright: ignore[reportUnknownArgumentType]
        if len(seq) > _MAX_ITEMS:
            raise FreeTextError(f"audit metadata field {key!r} has more than {_MAX_ITEMS} items")
        return [_clean(key, v, depth + 1) for v in seq]
    raise FreeTextError(f"audit metadata field {key!r} has unsupported type {type(value).__name__}")


def _fields(fields: Mapping[Any, Any], depth: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise FreeTextError(f"audit metadata key {key!r} must be snake_case")
        if is_sensitive_key(key):
            raise FreeTextError(f"audit metadata key {key!r} names a content or secret field")
        out[key] = _clean(key, value, depth)
    return out


class AuditMeta(Mapping[str, Any]):
    """Validated, JSON-ready audit metadata. `AuditMeta(kind="org", chunks=3)` or `AuditMeta.of(mapping)`."""

    __slots__ = ("_data",)

    def __init__(self, **fields: Any) -> None:
        self._data = _fields(fields, 0)

    @classmethod
    def of(cls, fields: Mapping[str, Any] | None) -> AuditMeta:
        if isinstance(fields, AuditMeta):
            return fields
        return cls(**dict(fields or {}))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"AuditMeta({self._data!r})"

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)
