"""HPKE sealing (doc 13.2) and log redaction (doc 7.6) tests, with real cryptography."""

import json

import pytest

from lmqa_security.codes import CodeKind, generate
from lmqa_security.redaction import REDACTED, redact, scrub_text
from lmqa_security.sealing import SealError, generate_keypair, open_sealed, seal

pytestmark = [pytest.mark.unit, pytest.mark.stage1]
AAD = b"org=1|ws=2|event=3|month=2026-10"


def test_round_trip() -> None:
    pair = generate_keypair()
    payload = json.dumps({"question": "What is the notice period?"}).encode()
    sealed = seal(pair.public, payload, AAD)
    assert payload not in sealed
    assert open_sealed(pair.private, sealed, AAD) == payload


def test_sealing_is_randomized() -> None:
    pair = generate_keypair()
    assert seal(pair.public, b"same", AAD) != seal(pair.public, b"same", AAD)


def test_a_writer_holding_only_the_public_key_cannot_decrypt() -> None:
    pair = generate_keypair()
    sealed = seal(pair.public, b"secret", AAD)
    with pytest.raises(SealError):
        open_sealed(pair.public, sealed, AAD)  # the public key is not the private key


def test_the_wrong_private_key_fails() -> None:
    sealed = seal(generate_keypair().public, b"secret", AAD)
    with pytest.raises(SealError):
        open_sealed(generate_keypair().private, sealed, AAD)


def test_changed_associated_data_fails() -> None:
    pair = generate_keypair()
    sealed = seal(pair.public, b"secret", AAD)
    with pytest.raises(SealError):
        open_sealed(pair.private, sealed, AAD + b"x")


def test_tampering_is_detected_at_every_position() -> None:
    pair = generate_keypair()
    sealed = seal(pair.public, b"secret payload", AAD)
    for index in range(len(sealed)):
        broken = sealed[:index] + bytes([sealed[index] ^ 0x01]) + sealed[index + 1 :]
        with pytest.raises(SealError):
            open_sealed(pair.private, broken, AAD)


def test_truncated_blob_is_rejected() -> None:
    pair = generate_keypair()
    with pytest.raises(SealError):
        open_sealed(pair.private, b"\x00" * 10, AAD)


def test_destroying_the_private_key_makes_old_payloads_unreadable() -> None:
    old, new = generate_keypair(), generate_keypair()
    sealed = seal(old.public, b"month one", AAD)
    del old
    with pytest.raises(SealError):
        open_sealed(new.private, sealed, AAD)


def test_redact_removes_sensitive_fields_at_any_depth() -> None:
    event = {
        "event": "join",
        "admin_code": "abc",
        "Authorization": "Bearer abc.def",
        "nested": {"password": "p", "ok": 1, "items": [{"api_key": "k"}, "fine"]},
    }
    out = redact(event)
    assert out["admin_code"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert out["nested"]["items"][0]["api_key"] == REDACTED
    assert out["nested"]["items"][1] == "fine"
    assert out["nested"]["ok"] == 1
    assert event["admin_code"] == "abc", "redact returns a copy"


@pytest.mark.parametrize("kind", list(CodeKind))
def test_a_code_pasted_into_free_text_is_scrubbed_in_both_forms(kind: CodeKind) -> None:
    code = generate(kind)
    for form in (code.display, code.canonical, code.display.lower(), code.canonical.lower()):
        assert (
            scrub_text(f"user pasted {form} into the form")
            == f"user pasted {REDACTED} into the form"
        )


def test_ordinary_log_text_is_left_alone() -> None:
    line = "request 7f3c9a1e-4b2d-4c5e-8f6a-1b2c3d4e5f60 took 12 ms for workspace main"
    assert scrub_text(line) == line


def test_bearer_tokens_and_jwts_are_scrubbed() -> None:
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlMTIz"
    assert jwt not in scrub_text(f"token={jwt}")
    assert "abc123" not in scrub_text("Authorization: Bearer abc123")
