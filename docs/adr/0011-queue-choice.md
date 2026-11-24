# ADR 0011: Background job queue

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 4.5, 4.8, 9.3, 10.3, 10.8, 22; decision D18; gate G0.13 (also G1.7, G4.7, G4.8, G4.12)

## Context

Ingestion (scan, parse, OCR, chunk, embed), re-indexing and identity saga steps run as background jobs. A job
must never run before the transaction that created its document commits, and must not exist if that
transaction rolls back (9.3). One workspace's large upload must not starve others (10.8). The request path
goes through PgBouncer in transaction pooling mode, which breaks session state: `LISTEN`/`NOTIFY`, session
advisory locks and prepared statements without pooler support (4.8).

## Decision

- D18: Procrastinate, a PostgreSQL-backed queue. Jobs are plain tables and SQL functions.
- Enqueue: the application calls Procrastinate's SQL defer function inside its own transaction, through the
  pooler, as the request-path role. The job row commits or rolls back with the document row (outbox pattern).
- Workers connect to PostgreSQL directly (not through the pooler) so they can use `LISTEN`/`NOTIFY` and
  session locks. They still set the transaction-local context from the signed job envelope for every
  transaction (DEF-53).
- Fair share: each workspace has N job-lock slots `ws:{id}:slot:{k}` (N = its concurrency cap), so no single
  lock serializes a workspace and a flood in one workspace cannot starve another.
- Fallback: Celery 5.6 if the spike failed. Arq is excluded (no longer actively maintained).

## Alternatives considered

- Celery with a Redis-protocol broker: enqueue is not part of the database transaction, so "job ran before
  commit" and "job for a rolled-back row" races need extra outbox machinery. Kept as fallback only.
- Arq: rejected, unmaintained.
- A hand-written `SELECT ... FOR UPDATE SKIP LOCKED` queue: rejected; Procrastinate already provides retries,
  locks and `NOTIFY` wake-up on the same mechanism.

## Consequences

- Positive: transactional enqueue with no extra broker; one fewer system to secure and back up.
- Negative: queue load lands on PostgreSQL; workers need direct connections and a separate role.
- Proven by G0.13 (below), and later by G4.7 (job safety), G4.8 (fairness under flood) and G4.12 (throughput).

## Current state

G0.13 passed on 2026-11-22 with Procrastinate 3.12.0 through PgBouncer 1.26.1 (transaction pooling,
`max_prepared_statements=200`) and PostgreSQL 18.7:

1. Transactional enqueue: calling the SQL function `procrastinate_defer_jobs_v2` through the pooler as the
   request-path role `lmqa_app` left the job invisible before commit and absent after rollback.
2. Fair share: per-workspace slot locks `ws:{id}:slot:{k}` with N slots bounded concurrency to exactly N per
   workspace, while a second workspace ran alongside a flooding one.
3. `NOTIFY`: a worker on a direct connection (role `lmqa_system`) started a job within 2 s of commit while its
   polling interval was 120 s.
4. Throughput: floor of 10 no-op jobs/s on one worker with concurrency 4, derived from the Stage 4 budget. A
   200-page document within 10 minutes is 0.33 jobs/s per document with one job per page; 30 documents in
   flight is 10 jobs/s. It passed on a 2-core reference machine.

Celery is therefore not adopted. Test: `tests/integration/test_stage0_queue_spike.py`, which uses a throwaway
database `lmqa_spike`. Versions are in [docs/versions.md](../versions.md).

The product does not use the queue yet. MVP ingestion runs on an in-process thread pool (2 workers) inside the
gateway process, and documents left `processing` by a restart are resumed at startup
(`services/ingestion/src/ingestion/pipeline.py`); there is no per-workspace fair share and no signed envelope
(deviations 1 and 9 in [docs/mvp.md](../mvp.md)). Stage 4 moves ingestion onto Procrastinate with signed job
envelopes (G4.7, G4.8).
