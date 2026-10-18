from __future__ import annotations

import os

# Force these unconditionally (not setdefault) — tests must be deterministic
# regardless of whether a real .env has already been sourced into this shell
# (e.g. after the Gemini smoke test). A test suite that silently inherits
# whatever secret happens to be in the ambient environment is not a reliable
# test suite.
os.environ["APP_SECRET_KEY"] = "test-secret-value-32-bytes-long!!"
os.environ["FIELD_ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["INTERNAL_SERVICE_API_KEY"] = "test-internal-key"
os.environ["ENVIRONMENT"] = "local"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["COMPRESSION_BACKEND"] = "whitespace"
os.environ["TOKEN_COUNTER_BACKEND"] = "approx"
os.environ["SEMANTIC_CACHE_BACKEND"] = "in-memory"
os.environ["PROMPT_REGISTRY_BACKEND"] = "local-file"
os.environ["PROMPT_TEMPLATES_DIR"] = "/tmp/legalmed-test-prompts-empty"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.state import AppState


@pytest_asyncio.fixture
async def client():
    app.state.legalmed = await AppState.create()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def internal_headers():
    return {"X-Internal-Service-Key": "test-internal-key"}
