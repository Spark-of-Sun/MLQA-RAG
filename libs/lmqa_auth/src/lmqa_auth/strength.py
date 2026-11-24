"""Authentication-strength names (design 8.4, R-21.2, DEV-41).

The post-login Action (`infra/auth0/actions/post-login.js`) computes one of these names from the methods Auth0
records and puts it in the `<ns>/auth_strength` claim. The Gateway only compares names through this module:

* `passkey`       a passkey was the first factor
* `webauthn_mfa`  password plus a WebAuthn second factor (security key or platform authenticator)
* `otp_mfa`       password plus a TOTP (or other non-WebAuthn) second factor
* `password`      password only

`passkey` and `webauthn_mfa` are phishing-resistant and rank equal; privileged principals need one of them.
"""

from __future__ import annotations

PASSKEY = "passkey"
WEBAUTHN_MFA = "webauthn_mfa"
OTP_MFA = "otp_mfa"
PASSWORD = "password"  # noqa: S105 - a strength name, not a secret

AUTH_STRENGTHS: tuple[str, ...] = (PASSKEY, WEBAUTHN_MFA, OTP_MFA, PASSWORD)
PHISHING_RESISTANT: frozenset[str] = frozenset({PASSKEY, WEBAUTHN_MFA})
RANK: dict[str, int] = {PASSWORD: 0, OTP_MFA: 1, WEBAUTHN_MFA: 2, PASSKEY: 2}


def normalize(value: object) -> str:
    """A known strength name, or `password` (the weakest) for anything missing or unknown."""
    return value if isinstance(value, str) and value in RANK else PASSWORD


def at_least(strength: str, required: str) -> bool:
    """True when `strength` meets `required`. An unknown `required` name is a programming error."""
    return RANK.get(strength, 0) >= RANK[required]
