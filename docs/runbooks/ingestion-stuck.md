# Runbook: Ingestion stuck (document not progressing past "ingesting")

## Symptoms

- `GET /v1/documents/{id}` keeps returning `status: ingesting` well past
  the expected time for the document's page count.
- `docs/runbooks` note: even in local/demo mode, this can happen — the
  worker pool is a real async pipeline, not a stub.

## Likely causes, in order of likelihood

1. **Worker pool is not running or crashed.**
   - Check: `make logs s=ingestion-worker`
   - Local fix: `docker compose restart ingestion-worker`
   - Production: check the worker pool's HPA and recent deploys; confirm
     queue depth isn't silently capped.

2. **Redis/queue backend unreachable.**
   - `ingestion` and `ingestion-worker` share a queue over Redis locally
     (SQS in some production configs). If Redis is down, jobs enqueue but
     never get picked up.
   - Check: `docker compose ps redis` is healthy; `WORKER_QUEUE_BACKEND`
     in `.env` matches what's actually running.

3. **OCR step stuck on a specific page.**
   - Low-confidence or malformed scans can hang Tesseract on a page.
   - Check `services/ingestion/app/ocr` logs for the specific
     `document_id`; look for a per-page timeout being hit repeatedly.
   - Confirm `OCR_LOW_CONFIDENCE_THRESHOLD` isn't set so low that every
     page is being retried instead of flagged for human review.

4. **Embedding model failed to load (CPU checkpoint missing/OOM).**
   - Local mode defaults to a CPU-friendly embedding checkpoint
     (`EMBEDDING_MODEL`, `EMBEDDING_DEVICE=cpu` in `.env`). A missing model
     cache or an undersized container will stall every job behind it.
   - Check: `docker compose logs ingestion-worker | grep -i embedding`

5. **Vector DB (Qdrant) or object storage (MinIO) unreachable.**
   - The last step of ingestion writes to both. If either is down, the
     job will retry and the document stays `ingesting`.
   - Check: `docker compose ps qdrant minio` are healthy;
     `minio-init` completed successfully (bucket exists).

## Diagnostic steps

```bash
# 1. Confirm the worker pool is up and has picked up the job
make logs s=ingestion-worker

# 2. Check the job's current stage directly (document_id from the UI/API)
docker compose exec ingestion python -m app.workers.inspect_job <document_id>

# 3. Check queue depth
docker compose exec redis redis-cli llen ingestion:jobs

# 4. Check Qdrant and MinIO health
curl -s http://localhost:6333/readyz
docker compose exec minio mc ready local
```

## Resolution

- If the worker pool was down: restart it, confirm the job resumes from
  its last completed stage (ingestion is checkpointed per stage: OCR →
  chunk → embed → write).
- If a single page is poisoning OCR: the document's per-page confidence
  scores should show the stuck page; mark it for manual review via the
  document library UI rather than retrying indefinitely.
- If this is systemic (many documents stuck, not one): treat as an
  incident — page the on-call owner for `ingestion`, check recent deploys
  to `services/ingestion`, and consider pausing new uploads at the
  Gateway until resolved.

## Escalation

If stuck jobs correlate with a specific tenant's confidentiality tier or
matter/patient scope, escalate immediately — this can indicate a tenant
isolation bug in the embedding/write path, not just a performance issue.

