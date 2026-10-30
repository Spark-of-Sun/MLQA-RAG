"""Join codes (doc section 7.6): generation, check character, normalization, keyed hashing.

Layout (Crockford Base32, upper case, shown in groups of 8):

* Organization Code, 64 characters: 8 public lookup ID + 55 secret + 1 check. Secret entropy
  55 x 5 = 275 bits.
* Admin Code, 32 characters: 8 public lookup ID + 23 secret + 1 check. Secret entropy
  23 x 5 = 115 bits.

The lookup ID is stored in plaintext, so only the secret portion counts as entropy (DEF-11).
The stored value is a keyed HMAC-SHA-256 of kind and full code under a versioned server-side
pepper, never the code itself. The last characters are never shown again after creation.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
"""Crockford Base32: no I, L, O or U."""
BASE: Final = len(ALPHABET)
LOOKUP_LENGTH: Final = 8
GROUP: Final = 8
_ALIASES: Final = {"I": "1", "L": "1", "O": "0"}


class CodeKind(StrEnum):
    """Which secret a code is. The kind is part of what gets hashed."""

    ORGANIZATION = "org"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class CodeSpec:
    """Length and entropy of one kind of code."""

    length: int

    @property
    def secret_length(self) -> int:
        """Number of secret characters (everything but lookup ID and check character)."""
        return self.length - LOOKUP_LENGTH - 1

    @property
    def secret_bits(self) -> int:
        """Entropy of the secret portion in bits (5 per Base32 character)."""
        return self.secret_length * 5


SPECS: Final = {CodeKind.ORGANIZATION: CodeSpec(64), CodeKind.ADMIN: CodeSpec(32)}


class InvalidCodeError(ValueError):
    """Raised for a malformed code. Callers show one uniform message regardless of the reason."""


@dataclass(frozen=True, slots=True)
class GeneratedCode:
    """A new code. ``display`` is shown once and never stored."""

    kind: CodeKind
    canonical: str
    lookup_id: str

    @property
    def display(self) -> str:
        """The code in groups of eight characters, separated by dashes."""
        return "-".join(self.canonical[i : i + GROUP] for i in range(0, len(self.canonical), GROUP))


def luhn_mod_n_check(payload: str) -> str:
    """Return the Luhn mod-32 check character for ``payload``."""
    factor, total = 2, 0
    for char in reversed(payload):
        addend = factor * ALPHABET.index(char)
        factor = 1 if factor == 2 else 2  # noqa: PLR2004 - Luhn alternates 2, 1
        total += addend // BASE + addend % BASE
    return ALPHABET[(BASE - total % BASE) % BASE]


def is_check_valid(code: str) -> bool:
    """True if the final character is the correct Luhn mod-32 check for the rest."""
    return len(code) > 1 and luhn_mod_n_check(code[:-1]) == code[-1]


def generate(kind: CodeKind) -> GeneratedCode:
    """Create a code from the operating system CSPRNG."""
    spec = SPECS[kind]
    body = "".join(secrets.choice(ALPHABET) for _ in range(spec.length - 1))
    canonical = body + luhn_mod_n_check(body)
    return GeneratedCode(kind=kind, canonical=canonical, lookup_id=canonical[:LOOKUP_LENGTH])


def normalize(raw: str, kind: CodeKind) -> str:
    """Canonicalize user input: drop separators, upper-case, apply Crockford aliases.

    Raises:
        InvalidCodeError: wrong length, a character outside the alphabet, or a bad check
            character. The client runs the same check so typos never cost a server attempt.
    """
    cleaned = "".join(ch for ch in raw.upper() if ch not in "- _\t\r\n")
    cleaned = "".join(_ALIASES.get(ch, ch) for ch in cleaned)
    if len(cleaned) != SPECS[kind].length or any(ch not in ALPHABET for ch in cleaned):
        msg = "malformed code"
        raise InvalidCodeError(msg)
    if not is_check_valid(cleaned):
        msg = "check character mismatch"
        raise InvalidCodeError(msg)
    return cleaned


def hash_code(kind: CodeKind, canonical: str, pepper: bytes) -> bytes:
    """Keyed HMAC-SHA-256 over ``kind`` and the full code under a server-side pepper."""
    if len(pepper) < 32:  # noqa: PLR2004 - minimum pepper size in bytes
        msg = "pepper must be at least 32 bytes"
        raise ValueError(msg)
    return hmac.new(pepper, f"{kind.value}:{canonical}".encode(), hashlib.sha256).digest()


def matches(stored: bytes, kind: CodeKind, canonical: str, pepper: bytes) -> bool:
    """Compare a candidate to a stored hash in constant time."""
    return hmac.compare_digest(stored, hash_code(kind, canonical, pepper))
