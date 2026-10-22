from __future__ import annotations

import os
from typing import ClassVar

from arq.connections import RedisSettings

from app.workers.tasks import ingest_document


class WorkerSettings:
    functions: ClassVar[list] = [ingest_document]

    # Must match JobQueue's resolution order exactly (app/state.py) —
    # enqueue side and consume side have to agree on which Redis DB
    # they're using, or jobs enqueue successfully and are never picked
    # up (see docs/runbooks/ingestion-stuck.md, "Redis/queue backend
    # unreachable" — same symptom, different root cause: DB mismatch
    # rather than Redis being down).
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("INGESTION_REDIS_URL")
        or os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
    max_jobs = int(os.environ.get("WORKER_CONCURRENCY", "4"))
