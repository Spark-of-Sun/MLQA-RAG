# ADR 0007: Real data and no mocks

**Status:** Accepted

## Decision
Tests use real PostgreSQL, PgBouncer, Valkey, Qdrant, an S3 store, OpenBao/KMS and real public documents from `corpus/manifest.toml`. ruff bans mock/fake libraries. Negative controls (EICAR, hostile XML, forged tokens) are labelled instruments.

## Why
A mocked store cannot prove an isolation property. Result in this build: real servers found about a dozen defects a mock would have hidden (see the work log).
