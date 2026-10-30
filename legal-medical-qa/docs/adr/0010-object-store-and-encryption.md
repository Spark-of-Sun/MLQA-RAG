# ADR 0010: Object store and encryption

**Status:** Accepted

## Decision
Objects are encrypted by the application (AES-256-GCM, 1 MiB segments with a final-segment marker) under the per-document key, so behaviour is identical locally and in production. SeaweedFS locally (passed the capability probe); S3 in production.

## Why
MinIO's community edition is in maintenance mode; server-side encryption hooks differ between S3-compatible stores.
