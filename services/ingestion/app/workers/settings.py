from __future__ import annotations

import os

from arq.connections import RedisSettings

from app.workers.tasks import ingest_document


class WorkerSettings:
    functions = [ingest_document]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    max_jobs = int(os.environ.get("WORKER_CONCURRENCY", "4"))
