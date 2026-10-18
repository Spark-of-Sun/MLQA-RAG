from __future__ import annotations

import os

os.environ["APP_SECRET_KEY"] = "test-secret-value-32-bytes-long!!"
os.environ["FIELD_ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["INTERNAL_SERVICE_API_KEY"] = "test-internal-key"
os.environ["JWT_ISSUER"] = "legalmed-local"
os.environ["JWT_AUDIENCE"] = "legalmed-services"
os.environ["ENVIRONMENT"] = "local"

import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from common.auth.jwt import create_session_jwt
from common.models import Action, RoleScope

from app.main import app
from app.state import AppState, ServiceClients


class FakeServiceClients(ServiceClients):
    """Overrides the real HTTP calls with canned responses so gateway
    tests don't depend on retrieval/generation/citation_validator
    actually running — those services don't exist yet.
    """

    def __init__(self) -> None:  # intentionally skip ServiceClients.__init__
        pass

    async def search(self, **payload):
        return {
            "query": payload["query"],
            "chunks": [
                {
                    "chunk_id": "c1",
                    "document_id": "doc1",
                    "text": "The term of this agreement is 12 months.",
                    "page": 4,
                    "section": "4.2",
                }
            ],
            "dropped_chunk_count": 0,
        }

    async def generate_stream(self, payload):
        yield json.dumps({"type": "token", "token": "The "})
        yield json.dumps(
            {
                "type": "final",
                "final": {
                    "answer_text": "The term is 12 months. [chunk_c1]",
                    "chunk_ids_in_context": ["c1"],
                    "dropped_chunk_ids": [],
                    "prompt_tokens": 42,
                    "completion_tokens": 8,
                    "cache_hit": False,
                },
            }
        )

    async def validate(self, **payload):
        return {
            "validation_outcome": "pass",
            "verified_answer_text": "The term is 12 months. [1]",
            "resolved_citations": [{"chunk_id": "c1", "document_id": "doc1", "page": 4, "section": "4.2"}],
            "findings": [],
        }

    async def aclose(self) -> None:
        pass


@pytest_asyncio.fixture
async def client():
    # NOTE: ASGITransport doesn't run FastAPI's lifespan handler, so we set
    # app.state.legalmed manually instead of relying on startup to create it.
    app.state.legalmed = AppState(FakeServiceClients())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_header():
    def _make(tenant_id="t1", matter_or_patient_id="matter-1", action=Action.QUERY, user_id="u1"):
        role = RoleScope(tenant_id=tenant_id, matter_or_patient_id=matter_or_patient_id, action=action)
        token = create_session_jwt(user_id=user_id, tenant_id=tenant_id, roles=[role])
        return {"Authorization": f"Bearer {token}"}

    return _make

