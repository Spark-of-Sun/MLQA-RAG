"""Unit tests for log redaction (R-16 criterion 10, R-60 criterion 5)."""

from __future__ import annotations

import base64
import io
import json
import logging
from collections.abc import Iterator

import pytest

from lmqa_security.codes import generate
from lmqa_security.redact import MASK, install, redact, redact_text, redact_value

pytestmark = pytest.mark.stage3


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# A JWT-shaped sample built at run time, so the repository holds no token literal for the secret scanner to flag.
JWT = ".".join(
    [
        _b64(json.dumps({"alg": "ES256"}).encode()),
        _b64(json.dumps({"sub": "user-1"}).encode()),
        _b64(b"signature"),
    ]
)


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["org", "admin"])
def test_join_codes_are_redacted_raw_and_in_display_form(kind: str) -> None:
    code = generate(kind)  # type: ignore[arg-type]
    for form in (code.code, code.display):
        out = redact_text(f"redeeming {form} for user 7")
        assert form not in out
        assert MASK in out
        assert out.endswith("for user 7")


@pytest.mark.unit
def test_bearer_jwt_and_context_tokens_are_redacted() -> None:
    out = redact_text(f"Authorization: Bearer abc.def-ghi and X-Context-Token={JWT} raw {JWT}")
    assert "abc.def-ghi" not in out
    assert JWT not in out
    assert "eyJ" not in out


@pytest.mark.unit
def test_content_and_contact_keys_are_redacted() -> None:
    out = redact_text(
        'payload {"title": "Smith v. Jones", "question": "is the dose safe?", "chunk_id": "c1"} '
        "email=alice@example.com phone: 555-0100 answer='take two'"
    )
    for secret in (
        "Smith v. Jones",
        "is the dose safe?",
        "alice@example.com",
        "555-0100",
        "take two",
    ):
        assert secret not in out
    assert '"chunk_id": "c1"' in out


@pytest.mark.unit
def test_plain_operational_text_is_kept() -> None:
    text = "indexed document 3f2a: 12 chunks with bge-small, 4 embeddings reused"
    assert redact_text(text) == text


@pytest.mark.unit
def test_redact_value_masks_sensitive_keys_and_recurses() -> None:
    out = redact_value(
        {"code": "X", "nested": {"access_token": "t", "ids": ["a", JWT]}, "count": 3}
    )
    assert out == {"code": MASK, "nested": {"access_token": MASK, "ids": ["a", MASK]}, "count": 3}


@pytest.mark.unit
def test_redact_record_covers_args_extra_and_exception() -> None:
    try:
        raise ValueError(f"bad token {JWT}")
    except ValueError:
        import sys

        exc = sys.exc_info()
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "user %s sent %s", ("u1", JWT), exc)
    record.__dict__["question"] = "what is the diagnosis?"
    redact(record)
    assert record.getMessage() == f"user u1 sent {MASK}"
    assert record.__dict__["question"] == MASK
    assert record.exc_text is not None
    assert JWT not in record.exc_text
    assert "ValueError" in record.exc_text


@pytest.fixture
def factory() -> Iterator[None]:
    previous = logging.getLogRecordFactory()
    yield
    logging.setLogRecordFactory(previous)


@pytest.mark.unit
@pytest.mark.usefixtures("factory")
def test_install_redacts_every_logger_and_is_idempotent() -> None:
    install()
    first = logging.getLogRecordFactory()
    install()
    assert logging.getLogRecordFactory() is first
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    log = logging.getLogger("lmqa.test.redact")
    log.addHandler(handler)
    log.propagate = False
    try:
        log.warning("join with code=%s", generate("admin").code)
    finally:
        log.removeHandler(handler)
    assert stream.getvalue().strip() == f"join with code={MASK}"
