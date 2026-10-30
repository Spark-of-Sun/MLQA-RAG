# ADR 0011: Queue choice

**Status:** Proposed

## Decision
The design prefers Procrastinate (PostgreSQL-backed, enqueue inside the application's own transaction). The Stage 0 queue spike (gate G0.13) was NOT run in this build: ingestion currently runs as an in-process background task and a transactional outbox for re-indexing.

## Why
Decision pending G0.13. If the spike fails (pooler, NOTIFY, per-workspace slot locks), the fallback is Celery 5.6.
