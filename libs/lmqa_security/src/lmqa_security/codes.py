"""Organization Codes (64 chars) and Admin Codes (32 chars), blueprint section 7.6.

Layout: 8-character public lookup ID + secret characters + 1 Luhn mod-32 check character, in Crockford
Base32. Only a keyed HMAC-SHA-256 of kind + full code is stored, with a versioned server-side pepper.
The plaintext is returned once to its owner and never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Literal

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_INDEX = {ch: i for i, ch in enumerate(ALPHABET)}
_ALIASES = str.maketrans({"O": "0", "I": "1", "L": "1"})

Kind = Literal["org", "admin"]
LENGTH: dict[Kind, int] = {"org": 64, "admin": 32}
LOOKUP_LEN = 8


@dataclass(frozen=True)
class NewCode:
    kind: Kind
    code: str  # plaintext, show once
    lookup_id: str

    @property
    def display(self) -> str:
        return "-".join(self.code[i : i + 8] for i in range(0, len(self.code), 8))


def _luhn_check_char(payload: str) -> str:
    n = len(ALPHABET)
    factor, total = 2, 0
    for ch in reversed(payload):
        addend = factor * _INDEX[ch]
        factor = 1 if factor == 2 else 2
        total += addend // n + addend % n
    return ALPHABET[(n - total % n) % n]


def luhn_valid(code: str) -> bool:
    n = len(ALPHABET)
    factor, total = 1, 0
    for ch in reversed(code):
        if ch not in _INDEX:
            return False
        addend = factor * _INDEX[ch]
        factor = 2 if factor == 1 else 1
        total += addend // n + addend % n
    return total % n == 0


def normalize(raw: str) -> str:
    """Upper-case, drop separators and map the look-alikes Crockford allows (O->0, I/L->1)."""
    return "".join(ch for ch in raw.upper() if ch not in " -_\t\r\n").translate(_ALIASES)


def generate(kind: Kind) -> NewCode:
    body = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH[kind] - 1))
    code = body + _luhn_check_char(body)
    return NewCode(kind=kind, code=code, lookup_id=code[:LOOKUP_LEN])


def parse(raw: str, kind: Kind) -> str | None:
    """Return the normalized code if its shape and check character are valid, else None."""
    code = normalize(raw)
    if len(code) != LENGTH[kind] or not luhn_valid(code):
        return None
    return code


def pepper_bytes(pepper: str) -> bytes:
    try:
        return bytes.fromhex(pepper)
    except ValueError:
        return pepper.encode("utf-8")


def code_hmac(pepper: str, kind: Kind, code: str) -> bytes:
    return hmac.new(pepper_bytes(pepper), f"{kind}:{code}".encode(), hashlib.sha256).digest()


def matches(pepper: str, kind: Kind, code: str, stored: bytes | None) -> bool:
    """Constant-time comparison; also burns the same work when no row was found."""
    expected = stored if stored is not None else b"\x00" * 32
    return hmac.compare_digest(code_hmac(pepper, kind, code), expected) and stored is not None
