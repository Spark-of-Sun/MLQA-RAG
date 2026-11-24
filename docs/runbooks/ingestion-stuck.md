# Runbook: Ingestion is stuck

1. Check the queue: `select status, count(*) from procrastinate_jobs group by status`.
2. Jobs in `doing` without a live worker are released by Procrastinate's stalled-worker pruning; restart `ingestion-worker` if none is running.
3. Documents in `ocr_review` wait for a person: they appear in the Review queue.
4. `index_outbox` rows in state `dead` raise the `outbox_dead` alert; fix the cause (Qdrant reachable? key valid?) and reset them to `pending`.
5. Run the reconciler for the workspace; it repairs missing, orphan and stale vectors.
