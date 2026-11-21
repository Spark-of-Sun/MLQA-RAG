"""G1.10 (envelope half): AES-256-GCM binding, tampering and streaming truncation."""

from dataclasses import replace
from uuid import uuid4

import pytest

from lmqa_keys import (
    Aad,
    DecryptionError,
    decrypt,
    decrypt_stream,
    encrypt,
    encrypt_stream,
    new_key,
)

pytestmark = [pytest.mark.unit, pytest.mark.stage1]
AAD = Aad(uuid4(), uuid4(), uuid4(), version=1, ordinal=3)


def test_round_trip_and_randomized_nonce() -> None:
    key = new_key()
    a, b = encrypt(key, b"clause 4.2", AAD), encrypt(key, b"clause 4.2", AAD)
    assert a != b
    assert decrypt(key, a, AAD) == decrypt(key, b, AAD) == b"clause 4.2"
    assert b"clause" not in a


@pytest.mark.parametrize("field", ["org_id", "workspace_id", "object_id"])
def test_ciphertext_copied_to_another_scope_fails(field: str) -> None:
    key = new_key()
    blob = encrypt(key, b"text", AAD)
    with pytest.raises(DecryptionError):
        decrypt(key, blob, replace(AAD, **{field: uuid4()}))


@pytest.mark.parametrize("change", [{"version": 2}, {"ordinal": 4}, {"ordinal": None}])
def test_ciphertext_copied_to_another_version_or_ordinal_fails(
    change: dict[str, int | None],
) -> None:
    key = new_key()
    blob = encrypt(key, b"text", AAD)
    with pytest.raises(DecryptionError):
        decrypt(key, blob, replace(AAD, **change))


def test_wrong_key_and_every_single_byte_tamper_fail() -> None:
    key = new_key()
    blob = encrypt(key, b"privileged text", AAD)
    with pytest.raises(DecryptionError):
        decrypt(new_key(), blob, AAD)
    for i in range(len(blob)):
        with pytest.raises(DecryptionError):
            decrypt(key, blob[:i] + bytes([blob[i] ^ 1]) + blob[i + 1 :], AAD)


def test_bad_key_length_and_short_ciphertext_are_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt(b"short", b"x", AAD)
    with pytest.raises(DecryptionError):
        decrypt(new_key(), b"tiny", AAD)


def test_aad_serialization_is_unambiguous() -> None:
    a = Aad(uuid4(), uuid4(), uuid4(), version=1, ordinal=None)
    assert a.to_bytes() != replace(a, ordinal=0).to_bytes()
    assert len(a.to_bytes()) == len(replace(a, ordinal=7).to_bytes())


@pytest.mark.parametrize("size", [0, 1, 63, 64, 65, 127, 128, 129, 1000])
def test_stream_round_trip_for_boundary_sizes(size: int) -> None:
    key, data = new_key(), bytes(range(256)) * 4
    data = data[:size]
    frames = list(
        encrypt_stream(key, [data[i : i + 10] for i in range(0, len(data), 10)], AAD, segment=64)
    )
    assert b"".join(decrypt_stream(key, frames, AAD)) == data


def test_stream_round_trip_with_real_one_mebibyte_segments() -> None:
    key = new_key()
    data = bytes(range(256)) * (4096 * 2 + 5)  # a little over 2 MiB
    frames = list(encrypt_stream(key, [data], AAD))
    assert len(frames) == 1 + 3, "prefix plus three segments"
    assert b"".join(decrypt_stream(key, frames, AAD)) == data


def _frames(data: bytes = b"A" * 400) -> tuple[bytes, list[bytes]]:
    key = new_key()
    return key, list(encrypt_stream(key, [data], AAD, segment=64))


def test_truncation_is_detected() -> None:
    key, frames = _frames()
    with pytest.raises(DecryptionError, match="truncated"):
        list(decrypt_stream(key, frames[:-1], AAD))


def test_reordering_and_dropping_a_middle_segment_are_detected() -> None:
    key, frames = _frames()
    swapped = [frames[0], frames[2], frames[1], *frames[3:]]
    with pytest.raises(DecryptionError):
        list(decrypt_stream(key, swapped, AAD))
    with pytest.raises(DecryptionError):
        list(decrypt_stream(key, [frames[0], *frames[2:]], AAD))


def test_data_after_the_final_segment_and_wrong_scope_are_detected() -> None:
    key, frames = _frames()
    with pytest.raises(DecryptionError, match="after the final"):
        list(decrypt_stream(key, [*frames, frames[1]], AAD))
    with pytest.raises(DecryptionError):
        list(decrypt_stream(key, frames, replace(AAD, workspace_id=uuid4())))
    with pytest.raises(DecryptionError):
        list(decrypt_stream(new_key(), frames, AAD))
    with pytest.raises(DecryptionError, match="empty"):
        list(decrypt_stream(key, [], AAD))
