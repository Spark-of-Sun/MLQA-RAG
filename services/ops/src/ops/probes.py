"""Operational health and readiness probes for core infrastructure."""

from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlparse

import asyncpg
from lmqa_db import DatabaseConfig
from lmqa_objectstore import ObjectStoreError, get_storage_client


async def check_database() -> tuple[bool, str]:
    """Verify database and PgBouncer connection."""
    cfg = DatabaseConfig.from_env()
    try:
        conn = await asyncpg.connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password or "lmqa_secret",
            database=cfg.database,
            timeout=3,
        )
        val = await conn.fetchval("SELECT 1")
        await conn.close()
    except (OSError, asyncpg.PostgresError) as e:
        return False, f"Database probe failed: {e}"
    else:
        if val == 1:
            return True, f"PostgreSQL/PgBouncer healthy at {cfg.host}:{cfg.port}"
        return False, "Unexpected response from database"


def check_tcp_port(host: str, port: int, timeout_sec: float = 2.0) -> bool:
    """Synchronously test if a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


async def check_valkey() -> tuple[bool, str]:
    """Verify Valkey cache reachability."""
    raw_url = os.environ.get("VALKEY_URL", "redis://localhost:6379/0")
    parsed = urlparse(raw_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379

    loop = asyncio.get_running_loop()
    is_open = await loop.run_in_executor(None, check_tcp_port, host, port, 2.0)
    if is_open:
        return True, f"Valkey reachable at {host}:{port}"
    return False, f"Valkey not reachable at {host}:{port}"


async def check_qdrant() -> tuple[bool, str]:
    """Verify Qdrant vector database reachability."""
    raw_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    parsed = urlparse(raw_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6333

    loop = asyncio.get_running_loop()
    is_open = await loop.run_in_executor(None, check_tcp_port, host, port, 2.0)
    if is_open:
        return True, f"Qdrant reachable at {host}:{port}"
    return False, f"Qdrant not reachable at {host}:{port}"


def check_storage() -> tuple[bool, str]:
    """Verify object store initialization and availability."""
    try:
        client = get_storage_client()
        exists = client.exists("documents", "probe-nonexistent.txt")
    except (OSError, ObjectStoreError) as e:
        return False, f"Storage probe failed: {e}"
    else:
        if exists:
            return True, "Storage probe responsive"
        return True, f"Storage client initialized ({client.__class__.__name__})"


async def check_all_probes() -> dict[str, object]:
    """Run all readiness checks and return health summary."""
    db_ok, db_msg = await check_database()
    valkey_ok, valkey_msg = await check_valkey()
    qdrant_ok, qdrant_msg = await check_qdrant()
    storage_ok, storage_msg = check_storage()

    all_ready = db_ok and storage_ok
    return {
        "status": "ready" if all_ready else "degraded",
        "components": {
            "database": {"ready": db_ok, "details": db_msg},
            "valkey": {"ready": valkey_ok, "details": valkey_msg},
            "qdrant": {"ready": qdrant_ok, "details": qdrant_msg},
            "storage": {"ready": storage_ok, "details": storage_msg},
        },
    }
