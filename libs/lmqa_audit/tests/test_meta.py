"""Unit tests for the audit metadata builder (R-60 criterion 5, R-16 criterion 10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pytest

from lmqa_audit.meta import AuditMeta, FreeTextError, check_token

pytestmark = pytest.mark.stage3


class Outcome(StrEnum):
    ANSWERED = "answered"


@pytest.mark.unit
def test_typed_enumerated_and_id_fields_are_accepted_and_json_ready() -> None:
    uid = uuid.uuid4()
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    meta = AuditMeta(
        user=uid,
        expires_at=at,
        outcome=Outcome.ANSWERED,
        chunks=3,
        verified=True,
        sha256="a" * 64,
        model="BAAI/bge-small-en-v1.5",
        lookup_id="7K3M9QXZ",
        shared_with=[str(uid)],
        dropped=[{"chunk_id": "c1", "reason": "budget"}],
        retrieval={"kept": 4, "rerank": "on", "embed_ms": 1.5},
    )
    assert meta["user"] == str(uid)
    assert meta["expires_at"] == at.isoformat()
    assert meta["outcome"] == "answered"
    assert meta.as_dict()["dropped"] == [{"chunk_id": "c1", "reason": "budget"}]
    assert AuditMeta.of(meta) is meta
    assert AuditMeta.of(None).as_dict() == {}


@pytest.mark.unit
@pytest.mark.parametrize(
    "fields",
    [
        {"reason": "patient is crashing, need access now"},
        {"note": "x"},
        {"title": "Smith"},
        {"question": "q"},
        {"answer": "a"},
        {"email": "a@b.c"},
        {"code": "7K3M9QXZ"},
        {"access_token": "t"},
        {"workspace_name": "Acme"},
        {"retrieval": {"detail_note": "focus on dosage"}},
        {"dropped": [{"reason": "too long to fit"}]},
        {"Reason": "ok"},
        {"blob": b"bytes"},
    ],
)
def test_free_text_and_content_keys_are_rejected_at_construction(fields: dict[str, Any]) -> None:
    with pytest.raises(FreeTextError):
        AuditMeta.of(fields)


@pytest.mark.unit
def test_check_token_rejects_whitespace() -> None:
    assert check_token("document.indexed", "action") == "document.indexed"
    with pytest.raises(FreeTextError):
        check_token("document indexed", "action")
