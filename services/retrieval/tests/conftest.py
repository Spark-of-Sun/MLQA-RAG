from __future__ import annotations

import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-value-32-bytes-long!!")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "test-encryption-key")
os.environ.setdefault("INTERNAL_SERVICE_API_KEY", "test-internal-key")
os.environ.setdefault("ENVIRONMENT", "local")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from common.models import Chunk, ConfidentialityTier

from app.main import app
from app.state import AppState, InMemoryVectorSearchBackend


def _make_chunk(chunk_id, text, tenant_id="t1", matter_or_patient_id="matter-1", tier=ConfidentialityTier.STANDARD):
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc1",
        tenant_id=tenant_id,
        matter_or_patient_id=matter_or_patient_id,
        text=text,
        page=1,
        section="4.2",
        confidentiality_tier=tier,
    )


@pytest_asyncio.fixture
async def client():
    backend = InMemoryVectorSearchBackend()
    backend.seed(
        [
            _make_chunk("c1", "The term of this agreement is 12 months."),
            _make_chunk("c2", "Either party may terminate with 30 days notice."),
            _make_chunk("c3", "Confidential information must not be disclosed."),
            _make_chunk("c4", "Outside tenant chunk", tenant_id="t-OTHER"),
            _make_chunk("c5", "Privileged chunk", tier=ConfidentialityTier.PRIVILEGED),
        ]
    )
    app.state.legalmed = AppState(backend)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def internal_headers():
    return {"X-Internal-Service-Key": "test-internal-key"}
