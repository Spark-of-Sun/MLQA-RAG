from __future__ import annotations

import os
from dataclasses import dataclass, field
from uuid import uuid4

import httpx

from common.models import AuditEvent, Tenant


class ServiceUnavailableError(Exception):
    """Raised when a downstream service (retrieval/generation/citation_validator)
    can't be reached. Routers turn this into a clear error, not a crash."""


@dataclass
class ServiceClients:
    """Thin async HTTP wrappers over the internal contracts in
    docs/api-contracts/{retrieval,generation,citation-validator}.yaml.
    Every call sets X-Internal-Service-Key — verified on the receiving
    side by common.auth.service_token.verify_internal_service_key.
    """

    retrieval_base_url: str
    generation_base_url: str
    citation_validator_base_url: str
    ingestion_base_url: str
    internal_key: str
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            headers={"X-Internal-Service-Key": self.internal_key},
            timeout=httpx.Timeout(30.0, connect=5.0),
        )

    async def search(self, **payload) -> dict:
        return await self._post(f"{self.retrieval_base_url}/internal/v1/search", payload)

    async def generate_stream(self, payload: dict):
        url = f"{self.generation_base_url}/internal/v1/generate"
        try:
            async with self._client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    # Generation's SSE lines are "data: {json}" — strip the
                    # SSE wire-format prefix before handing back a plain
                    # JSON string. The blank "\n\n" separator lines between
                    # events don't start with "data: " and are skipped here
                    # too, so there's no need for a separate empty-line check.
                    if line.startswith("data: "):
                        yield line[len("data: "):]
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(f"generation service error: {exc}") from exc
    

    async def validate(self, **payload) -> dict:
        return await self._post(f"{self.citation_validator_base_url}/internal/v1/validate", payload)

    async def _post(self, url: str, payload: dict) -> dict:
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(f"{url} unreachable or returned an error: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class InMemoryAuditRepository:
    """Temporary stand-in for the Postgres-backed, insert-only audit log
    (docs/architecture.md §6). Swap for a real repository once db/migrations
    exists — milestone 6 ('Audit trail + RBAC') in the build order. Every
    write here is lost on restart; never use this outside local dev.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    async def write(self, event: AuditEvent) -> None:
        self._events.append(event)

    async def search(
        self, tenant_id: str, user_id: str | None = None, session_id: str | None = None
    ) -> list[AuditEvent]:
        results = [e for e in self._events if e.tenant_id == tenant_id]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if session_id:
            results = [e for e in results if e.session_id == session_id]
        return results


class InMemoryTenantRepository:
    """Temporary stand-in for Postgres tenants/users/roles tables."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    async def list_all(self) -> list[Tenant]:
        return list(self._tenants.values())

    async def create(self, tenant: Tenant) -> Tenant:
        self._tenants[tenant.tenant_id] = tenant
        return tenant


class InMemoryDocumentRepository:
    """Temporary stand-in for Postgres document metadata, normally owned
    by the Ingestion service and mirrored here for the Gateway's listing
    endpoint. Swap for a real query once db/migrations + services/ingestion exist.
    """

    def __init__(self) -> None:
        self._documents: dict[str, dict] = {}

    async def list_for_scope(self, tenant_id: str, matter_or_patient_id: str | None) -> list[dict]:
        results = [d for d in self._documents.values() if d["tenant_id"] == tenant_id]
        if matter_or_patient_id:
            results = [d for d in results if d["matter_or_patient_id"] == matter_or_patient_id]
        return results

    async def get(self, document_id: str) -> dict | None:
        return self._documents.get(document_id)

    async def put_ingesting(
        self, tenant_id: str, filename: str, matter_or_patient_id: str, confidentiality_tier: str
    ) -> dict:
        document_id = str(uuid4())
        record = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "status": "ingesting",
            "matter_or_patient_id": matter_or_patient_id,
            "confidentiality_tier": confidentiality_tier,
        }
        self._documents[document_id] = record
        return record


class AppState:
    """Everything the Gateway needs for the lifetime of the process,
    created once in main.py's lifespan handler and attached to app.state.
    """

    def __init__(self, clients: ServiceClients) -> None:
        self.clients = clients
        self.audit_repo = InMemoryAuditRepository()
        self.tenant_repo = InMemoryTenantRepository()
        self.document_repo = InMemoryDocumentRepository()

    @classmethod
    async def create(cls) -> "AppState":
        clients = ServiceClients(
            retrieval_base_url=os.environ.get("RETRIEVAL_URL", "http://retrieval:8002"),
            generation_base_url=os.environ.get("GENERATION_URL", "http://generation:8003"),
            citation_validator_base_url=os.environ.get("CITATION_VALIDATOR_URL", "http://citation-validator:8004"),
            ingestion_base_url=os.environ.get("INGESTION_URL", "http://ingestion:8001"),
            internal_key=os.environ.get("INTERNAL_SERVICE_API_KEY", ""),
        )
        return cls(clients)

    async def aclose(self) -> None:
        await self.clients.aclose()

