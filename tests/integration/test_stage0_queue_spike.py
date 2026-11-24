"""G0.13 queue and connection routing spike (blueprint 4.5, 4.8, 10.3, D18, ADR 0011).

Through the real PgBouncer and PostgreSQL, with Procrastinate:
  1. the application enqueues inside its own transaction by calling the SQL defer function through the pooler:
     the job is invisible until commit and absent after rollback;
  2. per-workspace slot locks (`ws:{id}:slot:{k}`) bound each workspace's concurrency to its cap, and a flooding
     workspace does not starve another;
  3. a worker on a direct connection receives NOTIFY (it starts a job long before its polling interval);
  4. throughput: no-op jobs dispatch at or above the floor recorded in ADR 0011.

A throwaway database `lmqa_spike` is created for the run, so the product database is never touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import defaultdict
from collections.abc import Iterator
from importlib import resources

import procrastinate
import psycopg
import pytest
from psycopg import sql

from lmqa_db import connect_role as connect
from lmqa_db import dsn
from lmqa_models.settings import load_settings

pytestmark = [pytest.mark.stage0, pytest.mark.integration]

SPIKE_DB = "lmqa_spike"
QUEUE = "ingest"
# Stage 4 target (section 22): a 200-page document within 10 minutes. With one job per page that is 0.33 jobs/s per
# document; the floor allows 30 such documents in flight at once on one worker (30 x 200 / 600 s = 10 jobs/s), so
# queue overhead is never what makes ingestion miss its budget. Measured from the first job's start (ADR 0011).
THROUGHPUT_FLOOR = 10.0

_DEFER = """
select procrastinate_defer_jobs_v2(array[
    row(%(queue)s, %(task)s, 0, %(lock)s, null, %(args)s::jsonb, null, 'ordered')::procrastinate_job_to_defer_v2
])
"""


@pytest.fixture(scope="module")
def spike_db() -> Iterator[str]:
    settings = load_settings()
    with connect(settings, "postgres", autocommit=True) as conn:
        conn.execute(
            sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(SPIKE_DB))
        )
        conn.execute(
            sql.SQL("create database {} owner lmqa_owner").format(sql.Identifier(SPIKE_DB))
        )
    schema = resources.files("procrastinate.sql").joinpath("schema.sql").read_text(encoding="utf-8")
    with connect(settings, "lmqa_owner", database=SPIKE_DB, autocommit=True) as conn:
        conn.execute("revoke all on schema public from public")
        conn.execute(schema)  # type: ignore[arg-type] - the library's own reviewed DDL
        conn.execute(
            "create table spike_uploads (id bigserial primary key, workspace text not null)"
        )
        # Request path (lmqa_app through the pooler): may only defer jobs and write its own table.
        conn.execute("grant usage on schema public to lmqa_app, svc_ingestion")
        conn.execute("grant insert, select on procrastinate_jobs, spike_uploads to lmqa_app")
        conn.execute("grant insert on procrastinate_events to lmqa_app")
        conn.execute("grant usage on all sequences in schema public to lmqa_app")
        # Workers (svc_ingestion, direct connection): run the queue.
        conn.execute("grant all on all tables in schema public to svc_ingestion")
        conn.execute("grant usage on all sequences in schema public to svc_ingestion")
    yield SPIKE_DB
    with connect(settings, "postgres", autocommit=True) as conn:
        conn.execute(
            sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(SPIKE_DB))
        )


def _pooled() -> psycopg.Connection:
    return connect(
        load_settings(), "lmqa_app", database=SPIKE_DB, via_pooler=True, connect_timeout=5
    )


def _defer(conn: psycopg.Connection, task: str, lock: str | None, args: dict[str, object]) -> int:
    row = conn.execute(
        _DEFER, {"queue": QUEUE, "task": task, "lock": lock, "args": json.dumps(args)}
    ).fetchone()
    assert row is not None
    return int(row[0][0])


def _job_count(spike: str) -> int:
    with connect(load_settings(), "svc_ingestion", database=spike, connect_timeout=5) as conn:
        row = conn.execute("select count(*) from procrastinate_jobs").fetchone()
    return int(row[0]) if row else -1


def _clear(spike: str) -> None:
    with connect(load_settings(), "svc_ingestion", database=spike, autocommit=True) as conn:
        conn.execute("delete from procrastinate_events")
        conn.execute("delete from procrastinate_jobs")


def _app() -> procrastinate.App:
    worker_dsn = dsn(
        load_settings(), "svc_ingestion", database=SPIKE_DB
    )  # direct: LISTEN/NOTIFY needs a session
    return procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=worker_dsn))


def test_defer_is_transactional_through_the_pooler(spike_db: str) -> None:
    _clear(spike_db)
    with _pooled() as conn:
        with conn.transaction():
            conn.execute("insert into spike_uploads (workspace) values ('ws-a')")
            _defer(conn, "spike.noop", None, {"upload": 1})
            assert _job_count(spike_db) == 0, (
                "a job became visible before its transaction committed"
            )
        assert _job_count(spike_db) == 1
        with contextlib.suppress(RuntimeError), conn.transaction():
            _defer(conn, "spike.noop", None, {"upload": 2})
            raise RuntimeError("roll back")
    assert _job_count(spike_db) == 1, (
        "a job survived the rollback of the transaction that deferred it"
    )


async def _run_worker(
    app: procrastinate.App, *, concurrency: int, polling: float, until: asyncio.Event
) -> None:
    async with app.open_async():
        worker = asyncio.create_task(
            app.run_worker_async(
                queues=[QUEUE],
                concurrency=concurrency,
                wait=True,
                listen_notify=True,
                fetch_job_polling_interval=polling,
                install_signal_handlers=False,
                delete_jobs="always",
            )
        )
        await until.wait()
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


def test_slot_locks_bound_each_workspace_and_share_the_worker(spike_db: str) -> None:
    _clear(spike_db)
    caps = {"ws-a": 2, "ws-b": 1}
    jobs = {"ws-a": 8, "ws-b": 3}
    running: dict[str, int] = defaultdict(int)
    peak: dict[str, int] = defaultdict(int)
    finished: list[tuple[str, float]] = []
    total = sum(jobs.values())
    app = _app()
    done = asyncio.Event()

    @app.task(name="spike.work", queue=QUEUE)
    async def work(workspace: str) -> None:
        running[workspace] += 1
        peak[workspace] = max(peak[workspace], running[workspace])
        await asyncio.sleep(0.3)
        running[workspace] -= 1
        finished.append((workspace, time.monotonic()))
        if len(finished) == total:
            done.set()

    with _pooled() as conn, conn.transaction():
        # The flooding workspace enqueues first; fairness must still let ws-b run alongside it.
        for ws in ("ws-a", "ws-b"):
            for k in range(jobs[ws]):
                _defer(conn, "spike.work", f"ws:{ws}:slot:{k % caps[ws]}", {"workspace": ws})

    async def main() -> None:
        await asyncio.wait_for(_run_worker(app, concurrency=6, polling=0.5, until=done), timeout=60)

    asyncio.run(main())
    assert peak["ws-a"] == caps["ws-a"], (
        f"workspace A ran {peak['ws-a']} jobs at once, cap {caps['ws-a']}"
    )
    assert peak["ws-b"] == caps["ws-b"]
    last_a = max(t for ws, t in finished if ws == "ws-a")
    first_b = min(t for ws, t in finished if ws == "ws-b")
    assert first_b < last_a, "workspace B waited for workspace A's whole backlog"


def test_worker_on_a_direct_connection_receives_notify(spike_db: str) -> None:
    _clear(spike_db)
    app = _app()
    done = asyncio.Event()
    started: list[float] = []

    @app.task(name="spike.ping", queue=QUEUE)
    async def ping() -> None:
        started.append(time.monotonic())
        done.set()

    async def main() -> float:
        worker = asyncio.create_task(_run_worker(app, concurrency=1, polling=120.0, until=done))
        await asyncio.sleep(
            1.5
        )  # the worker has listened and found the queue empty; next poll is 120 s away
        t0 = time.monotonic()
        with _pooled() as conn, conn.transaction():
            _defer(conn, "spike.ping", None, {})
        await asyncio.wait_for(worker, timeout=20)
        return started[0] - t0

    latency = asyncio.run(main())
    assert latency < 2.0, (
        f"job started {latency:.2f} s after commit: NOTIFY did not reach the worker"
    )


def test_throughput_meets_the_floor(spike_db: str) -> None:
    _clear(spike_db)
    app = _app()
    count = 200
    done = asyncio.Event()
    seen: list[int] = []
    stamps: list[float] = []

    @app.task(name="spike.noop", queue=QUEUE)
    async def noop(i: int) -> None:
        stamps.append(time.monotonic())
        seen.append(i)
        if len(seen) == count:
            done.set()

    with _pooled() as conn, conn.transaction():
        for i in range(count):
            _defer(conn, "spike.noop", None, {"i": i})

    asyncio.run(
        asyncio.wait_for(_run_worker(app, concurrency=4, polling=0.5, until=done), timeout=60)
    )
    rate = (count - 1) / (max(stamps) - min(stamps))
    assert sorted(seen) == list(range(count))
    assert rate >= THROUGHPUT_FLOOR, f"{rate:.1f} jobs/s is below the floor of {THROUGHPUT_FLOOR}"
