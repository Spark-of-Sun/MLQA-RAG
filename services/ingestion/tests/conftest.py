"""Real components for ingestion tests: PostgreSQL, OpenBao, SeaweedFS, Qdrant, fastembed."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from ingestion.chunker import ChunkConfig, HfTokenizer
from ingestion.embedder import Embedder
from ingestion.pipeline import Components, IngestionPipeline
from ingestion.scanner import StaticChecks
from lmqa_db import ContextRole, Database, DbContext
from lmqa_keys import KeyService, OpenBaoProvider
from lmqa_objectstore import ObjectStore
from lmqa_testing import world
from lmqa_testing.fixtures import Stack
from lmqa_testing.pg import role_dsn
from lmqa_vectorstore import VectorReader, VectorWriter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(scope="session")
def tokenizer() -> HfTokenizer:
    return HfTokenizer("BAAI/bge-small-en-v1.5")


@pytest.fixture(scope="session")
def embedder() -> Embedder:
    return Embedder()


@dataclass
class Env:
    """One workspace with real keys, and the pipeline wired to every real service."""

    pipeline: IngestionPipeline
    components: Components
    reader: VectorReader
    ws: world.Workspace
    org: world.Org
    tenant: UUID
    owner: DbContext
    matter: UUID
    stack: Stack
    provider: OpenBaoProvider
    collection: str

    async def second_workspace(self) -> tuple[world.Workspace, DbContext]:
        ws = await world.create_workspace(self.stack, self.org)
        tenant = await world.create_tenant(self.stack, ws)
        await provision_keys(self.stack, self.components.keys, self.org, ws)
        return ws, world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant)


async def provision_keys(
    stack: Stack, keys: KeyService, org: world.Org, ws: world.Workspace
) -> None:
    async with stack.identity.scoped(world.SYSTEM) as s:
        existing = (
            await s.execute(
                text("SELECT kms_key_id FROM org_keys WHERE org_id = :o"), {"o": org.id}
            )
        ).scalar()
    if existing is None:
        ids = await keys.provision_org(org.id)
        cmk = ids.cmk_id
        async with stack.identity.scoped(world.SYSTEM) as s:
            await s.execute(
                text(
                    "INSERT INTO org_keys (org_id, kms_key_id, escrow_key_id) VALUES (:o, :k, :e)"
                ),
                {"o": org.id, "k": cmk, "e": ids.escrow_id},
            )
    else:
        cmk = str(existing)
    _key, wrapped = await keys.new_workspace_key(cmk, org.id, ws.id, 1)
    async with stack.identity.scoped(world.SYSTEM) as s:
        await s.execute(
            text(
                "INSERT INTO workspace_keys (org_id, workspace_id, version, wrapped_key)"
                " VALUES (:o, :w, 1, :k)"
            ),
            {"o": org.id, "w": ws.id, "k": wrapped},
        )


@pytest_asyncio.fixture
async def env(
    migrated_db: str, stack: Stack, tokenizer: HfTokenizer, embedder: Embedder
) -> AsyncGenerator[Env]:
    provider = OpenBaoProvider(
        os.environ.get("OPENBAO_ADDR", "http://127.0.0.1:8200"),
        os.environ.get("OPENBAO_TOKEN", "lmqa-dev-token"),
    )
    collection = f"lmqa_ing_{uuid4().hex[:10]}"
    url = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
    writer = VectorWriter(url, os.environ.get("QDRANT_KEY_RW", "lmqa-dev-rw-key"), collection)
    reader = VectorReader(url, os.environ.get("QDRANT_KEY_RO", "lmqa-dev-ro-key"), collection)
    await writer.ensure_collection(embedder.dimension)
    objects = ObjectStore(
        os.environ.get("OBJECT_STORE_ENDPOINT", "http://127.0.0.1:8333"),
        os.environ.get("OBJECT_STORE_ACCESS_KEY", "lmqa-dev-access"),
        os.environ.get("OBJECT_STORE_SECRET_KEY", "lmqa-dev-secret"),
        "lmqa-test-shared",
        "us-east-1",
    )
    await objects.ensure_bucket()
    db = Database(role_dsn("svc_ingestion", migrated_db), pooled=False, use_null_pool=True)
    keys = KeyService(provider)
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    tenant = await world.create_tenant(stack, ws)
    matter = await world.create_matter(stack, ws)
    await world.grant(stack, ws, tenant, matter, 3)
    await provision_keys(stack, keys, org, ws)
    components = Components(
        db,
        keys,
        objects,
        writer,
        embedder,
        StaticChecks(),
        tokenizer,
        ChunkConfig.for_embedding(512),
    )
    yield Env(
        IngestionPipeline(components),
        components,
        reader,
        ws,
        org,
        tenant,
        world.ctx(ContextRole.TENANT, ws.org, ws.id, tenant),
        matter,
        stack,
        provider,
        collection,
    )
    await writer.drop_collection()
    await writer.aclose()
    await reader.aclose()
    await db.dispose()
    await provider.aclose()
