"""Join code specification tests (doc 7.6, G2.5 library half)."""

import secrets

import pytest

from lmqa_security.codes import (
    ALPHABET,
    SPECS,
    CodeKind,
    InvalidCodeError,
    generate,
    hash_code,
    is_check_valid,
    matches,
    normalize,
)

pytestmark = [pytest.mark.unit, pytest.mark.stage1]
PEPPER = secrets.token_bytes(32)


def test_lengths_and_entropy_match_the_document() -> None:
    org, admin = SPECS[CodeKind.ORGANIZATION], SPECS[CodeKind.ADMIN]
    assert (org.length, admin.length) == (64, 32)
    assert (org.secret_length, admin.secret_length) == (55, 23)
    assert (org.secret_bits, admin.secret_bits) == (275, 115)  # DEF-11: not 315 / 155


@pytest.mark.parametrize("kind", list(CodeKind))
def test_generated_codes_are_well_formed(kind: CodeKind) -> None:
    code = generate(kind)
    assert len(code.canonical) == SPECS[kind].length
    assert set(code.canonical) <= set(ALPHABET)
    assert code.lookup_id == code.canonical[:8]
    assert is_check_valid(code.canonical)
    groups = code.display.split("-")
    assert all(len(g) == 8 for g in groups)
    assert len(groups) == SPECS[kind].length // 8


def test_alphabet_has_no_ambiguous_characters() -> None:
    assert len(ALPHABET) == 32
    assert not set("ILOU") & set(ALPHABET)


def test_codes_do_not_repeat() -> None:
    seen = {generate(CodeKind.ADMIN).canonical for _ in range(3000)}
    assert len(seen) == 3000


def test_every_character_of_every_position_can_appear() -> None:
    chars = set("".join(generate(CodeKind.ADMIN).canonical[8:-1] for _ in range(400)))
    assert chars == set(ALPHABET)


@pytest.mark.parametrize("kind", list(CodeKind))
def test_check_character_catches_every_single_character_typo(kind: CodeKind) -> None:
    code = generate(kind).canonical
    for pos in range(len(code)):
        for replacement in ALPHABET:
            if replacement == code[pos]:
                continue
            mutated = code[:pos] + replacement + code[pos + 1 :]
            assert not is_check_valid(mutated), (pos, replacement)


def test_check_character_catches_adjacent_transpositions() -> None:
    caught = total = 0
    for _ in range(300):
        code = generate(CodeKind.ADMIN).canonical
        for pos in range(len(code) - 1):
            if code[pos] == code[pos + 1]:
                continue
            swapped = code[:pos] + code[pos + 1] + code[pos] + code[pos + 2 :]
            total += 1
            caught += not is_check_valid(swapped)
    assert caught / total > 0.98  # Luhn mod N misses only the 0 <-> last-symbol swap


def test_normalize_accepts_display_form_and_crockford_aliases() -> None:
    code = generate(CodeKind.ADMIN)
    assert normalize(code.display, CodeKind.ADMIN) == code.canonical
    assert normalize(code.display.lower(), CodeKind.ADMIN) == code.canonical
    assert normalize(code.display.replace("-", "  "), CodeKind.ADMIN) == code.canonical


def test_normalize_maps_i_l_o_like_crockford() -> None:
    # Build a valid code whose canonical form contains 0 and 1, then type them as O and I / L.
    while True:
        code = generate(CodeKind.ADMIN).canonical
        if "0" in code and "1" in code:
            break
    typed = code.replace("0", "o").replace("1", "l")
    assert normalize(typed, CodeKind.ADMIN) == code


@pytest.mark.parametrize(
    "bad",
    ["", "short", "U" * 32, "0" * 31, "0" * 33, "!" * 32],
)
def test_normalize_rejects_malformed_input(bad: str) -> None:
    with pytest.raises(InvalidCodeError):
        normalize(bad, CodeKind.ADMIN)


def test_normalize_rejects_a_wrong_check_character() -> None:
    code = generate(CodeKind.ADMIN).canonical
    wrong = code[:-1] + ALPHABET[(ALPHABET.index(code[-1]) + 1) % 32]
    with pytest.raises(InvalidCodeError, match="check"):
        normalize(wrong, CodeKind.ADMIN)


def test_an_org_code_is_not_accepted_as_an_admin_code() -> None:
    with pytest.raises(InvalidCodeError):
        normalize(generate(CodeKind.ORGANIZATION).canonical, CodeKind.ADMIN)


def test_hash_is_keyed_and_bound_to_the_kind() -> None:
    code = generate(CodeKind.ADMIN).canonical
    base = hash_code(CodeKind.ADMIN, code, PEPPER)
    assert len(base) == 32
    assert hash_code(CodeKind.ADMIN, code, PEPPER) == base
    assert hash_code(CodeKind.ORGANIZATION, code, PEPPER) != base
    assert hash_code(CodeKind.ADMIN, code, secrets.token_bytes(32)) != base
    assert code.encode() not in base


def test_a_weak_pepper_is_refused() -> None:
    with pytest.raises(ValueError, match="pepper"):
        hash_code(CodeKind.ADMIN, generate(CodeKind.ADMIN).canonical, b"short")


def test_matches_is_true_only_for_the_right_code() -> None:
    right, wrong = generate(CodeKind.ADMIN).canonical, generate(CodeKind.ADMIN).canonical
    stored = hash_code(CodeKind.ADMIN, right, PEPPER)
    assert matches(stored, CodeKind.ADMIN, right, PEPPER)
    assert not matches(stored, CodeKind.ADMIN, wrong, PEPPER)
    assert not matches(stored, CodeKind.ORGANIZATION, right, PEPPER)
