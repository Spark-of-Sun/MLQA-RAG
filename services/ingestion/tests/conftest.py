from __future__ import annotations

import os

os.environ["APP_SECRET_KEY"] = "test-secret-value-32-bytes-long!!"
os.environ["FIELD_ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["INTERNAL_SERVICE_API_KEY"] = "test-internal-key"
os.environ["ENVIRONMENT"] = "local"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.state import AppState, JobQueue, ObjectStoreClient


class FakeObjectStoreClient(ObjectStoreClient):
    def __init__(self):  # intentionally skip ObjectStoreClient.__init__ (no real boto3 client)
        self._objects: dict[str, bytes] = {}

    def put_object(self, key: str, data: bytes) -> str:
        self._objects[key] = data
        return key

    def get_object(self, key: str) -> bytes:
        return self._objects[key]


class FakeJobQueue(JobQueue):
    def __init__(self):  # intentionally skip JobQueue.__init__ (no real Redis pool)
        self.enqueued: list[dict] = []

    async def enqueue_ingestion_job(self, **kwargs) -> None:
        self.enqueued.append(kwargs)

    async def aclose(self) -> None:
        pass


@pytest_asyncio.fixture
async def client():
    app.state.legalmed = AppState(FakeObjectStoreClient(), FakeJobQueue())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def internal_headers():
    return {"X-Internal-Service-Key": "test-internal-key"}

