"""Operational health and readiness probes for core infrastructure."""

from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlparse

import asyncpg
import httpx
from lmqa_db import DatabaseConfig
from lmqa_objectstore import ObjectStoreError, get_storage_client

HTTP_OK = 200


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


def check_valkey_ping(
    host: str, port: int, password: str | None = None, timeout_sec: float = 2.0
) -> tuple[bool, str]:
    """Test Valkey reachability and optional password authentication via PING."""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            sock.settimeout(timeout_sec)
            if password:
                sock.sendall(f"AUTH {password}\r\n".encode())
                auth_resp = sock.recv(1024).decode("utf-8", errors="replace")
                if not auth_resp.startswith("+OK"):
                    return False, f"Valkey authentication failed: {auth_resp.strip()}"
            sock.sendall(b"PING\r\n")
            ping_resp = sock.recv(1024).decode("utf-8", errors="replace")
            if "+PONG" in ping_resp:
                return True, f"Valkey healthy at {host}:{port}"
            return False, f"Valkey unexpected response: {ping_resp.strip()}"
    except OSError as e:
        return False, f"Valkey connection failed: {e}"


async def check_valkey() -> tuple[bool, str]:
    """Verify Valkey cache reachability and authentication."""
    raw_url = os.environ.get("VALKEY_URL", "redis://:password@localhost:6379/0")
    parsed = urlparse(raw_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    password = parsed.password or os.environ.get("VALKEY_PASSWORD")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, check_valkey_ping, host, port, password, 2.0)


async def check_qdrant() -> tuple[bool, str]:
    """Verify Qdrant vector database reachability and readiness."""
    raw_url = os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")
    api_key = (
        os.environ.get("QDRANT_KEY_RO")
        or os.environ.get("QDRANT_KEY_RW")
        or os.environ.get("QDRANT_API_KEY", "")
    )
    if api_key.startswith("python3 -c"):
        api_key = ""

    headers: dict[str, str] = {}
    if api_key:
        headers["api-key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{raw_url}/readyz", headers=headers)
            if resp.status_code == HTTP_OK:
                return True, f"Qdrant healthy and ready at {raw_url}"
            coll_resp = await client.get(f"{raw_url}/collections", headers=headers)
            if coll_resp.status_code == HTTP_OK:
                return True, f"Qdrant reachable at {raw_url}"
            return False, f"Qdrant returned HTTP {resp.status_code}"
    except (httpx.HTTPError, OSError) as e:
        return False, f"Qdrant probe failed: {e}"


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
