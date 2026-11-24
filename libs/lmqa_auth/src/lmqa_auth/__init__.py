"""Auth0 authenticates; PostgreSQL authorizes (blueprint 1.2). Internal trust: context tokens (9)."""

from lmqa_auth.context import (
    ContextClaims,
    ContextMinter,
    ContextTokenError,
    ContextVerifier,
    KmsTrustRoot,
    LocalTrustRoot,
    ReplayCache,
    Signer,
    SignerCertificate,
    sign_envelope,
    verify_envelope,
)
from lmqa_auth.strength import AUTH_STRENGTHS, PHISHING_RESISTANT
from lmqa_auth.verifier import Claims, TokenVerifier, Unauthorized

__all__ = [
    "AUTH_STRENGTHS",
    "PHISHING_RESISTANT",
    "Claims",
    "ContextClaims",
    "ContextMinter",
    "ContextTokenError",
    "ContextVerifier",
    "KmsTrustRoot",
    "LocalTrustRoot",
    "ReplayCache",
    "Signer",
    "SignerCertificate",
    "TokenVerifier",
    "Unauthorized",
    "sign_envelope",
    "verify_envelope",
]
