# ADR 0008: Context-token certificates

**Status:** Accepted

## Decision
Each Gateway instance signs 60 second, single-audience ES256 context tokens with an in-memory key certified for at most one hour by a KMS trust root; services verify the certificate, a deny-list and the audience.

## Why
Signing every request with KMS would add latency and hit quotas. Measured: 2000 tokens cost one trust-root call, p99 under 5 ms.
