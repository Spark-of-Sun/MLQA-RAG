from __future__ import annotations

import os

# Unconditional assignment, not setdefault — see services/generation's
# conftest.py fix: a test suite must never silently inherit a secret from
# whatever real .env happens to already be sourced into this shell.
os.environ["APP_SECRET_KEY"] = "test-secret-value-32-bytes-long!!"
os.environ["FIELD_ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["INTERNAL_SERVICE_API_KEY"] = "test-internal-key"
os.environ["ENVIRONMENT"] = "local"
os.environ["ENTAILMENT_BACKEND"] = "fake"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def internal_headers():
    return {"X-Internal-Service-Key": "test-internal-key"}
