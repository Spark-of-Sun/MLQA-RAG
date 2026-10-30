"""pytest fixtures: a real migrated PostgreSQL and real service-role connections (doc 19.1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

from lmqa_db import Database
from lmqa_testing.pg import fresh_database, role_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="session")
def db_name() -> str:
    """One database per xdist worker so parallel workers never share state."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return f"lmqa_test_{worker}"


@pytest.fixture(scope="session")
def migrated_db(db_name: str) -> str:
    """A fresh database with roles and every migration applied. Returns its name."""
    fresh_database(db_name)
    return db_name


@dataclass(frozen=True, slots=True)
class Stack:
    """One ``Database`` per service role, each connecting as that real login role."""

    gateway: Database
    identity: Database
    ingestion: Database
    retrieval: Database
    generation: Database
    validator: Database
    audit_reader: Database
    reconciler: Database


@pytest_asyncio.fixture
async def stack(migrated_db: str) -> AsyncGenerator[Stack]:
    """Connections as the real service roles (never a superuser)."""

    def make(role: str) -> Database:
        return Database(role_dsn(role, migrated_db), pooled=False, use_null_pool=True)

    s = Stack(
        gateway=make("svc_gateway"),
        identity=make("svc_identity"),
        ingestion=make("svc_ingestion"),
        retrieval=make("svc_retrieval"),
        generation=make("svc_generation"),
        validator=make("svc_validator"),
        audit_reader=make("svc_audit_reader"),
        reconciler=make("svc_reconciler"),
    )
    try:
        yield s
    finally:
        for db in (
            s.gateway,
            s.identity,
            s.ingestion,
            s.retrieval,
            s.generation,
            s.validator,
            s.audit_reader,
            s.reconciler,
        ):
            await db.dispose()
