# ADR 0009: Audit sealing

**Status:** Accepted

## Decision
Audit payloads are sealed (HPKE, X25519) to a workspace-month public key: writers can encrypt but never decrypt; only the audit service unwraps the private key. The hash chain commits to the ciphertext hash, so crypto-shredding a month never breaks verification.

## Why
One symmetric audit key available to every writer would let every service read every payload.
