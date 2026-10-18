from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from common.models import ConfidentialityTier, TenantIndustry


class ObjectStoreClient:
    """Thin boto3 wrapper pointed at MinIO locally / S3 in production —
    same client library both environments (docs/architecture.md §8)."""

    def __init__(self, endpoint_url: str | None = None, bucket: str | None = None):
        import boto3

        self._bucket = bucket or os.environ.get("S3_BUCKET", "legalmed-documents")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or os.environ.get("S3_ENDPOINT_URL"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )

    def put_object(self, key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    def get_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()


def build_object_store_client() -> ObjectStoreClient:
    return ObjectStoreClient()


class JobQueue:
    """Enqueues an ingestion job onto the Arq/Redis queue the worker pool
    (Dockerfile.worker) consumes from. Connection is lazy — constructing
    this doesn't touch Redis until the first enqueue call."""

    def __init__(self, redis_url: str | None = None):
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://redis:6379/0")
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            from arq import create_pool
            from arq.connections import RedisSettings

            self._pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        return self._pool

    async def enqueue_ingestion_job(self, **kwargs) -> None:
        pool = await self._get_pool()
        await pool.enqueue_job("ingest_document", **kwargs)

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()


class InMemoryDocumentRepository:
    """Source of truth for document metadata until db/migrations exists
    (milestone 1 in docs/architecture.md §9). Every write here is lost on
    restart — swap for the real Postgres-backed repository when it lands.
    """

    def __init__(self):
        self._documents: dict[str, dict] = {}

    async def create_ingesting(
        self,
        tenant_id: str,
        filename: str,
        matter_or_patient_id: str,
        confidentiality_tier: ConfidentialityTier,
        industry: TenantIndustry,
        object_store_key: str,
        effective_date=None,
    ) -> dict:
        document_id = str(uuid4())
        record = {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "status": "ingesting",
            "matter_or_patient_id": matter_or_patient_id,
            "confidentiality_tier": confidentiality_tier,
            "industry": industry,
            "object_store_key": object_store_key,
            "effective_date": effective_date,
            "uploaded_at": datetime.now(timezone.utc),
        }
        self._documents[document_id] = record
        return record

    async def get(self, document_id: str) -> dict | None:
        return self._documents.get(document_id)

    async def list_for_scope(self, tenant_id: str, matter_or_patient_id: str | None) -> list[dict]:
        results = [d for d in self._documents.values() if d["tenant_id"] == tenant_id]
        if matter_or_patient_id:
            results = [d for d in results if d["matter_or_patient_id"] == matter_or_patient_id]
        return results

    async def mark_status(self, document_id: str, status: str) -> None:
        if document_id in self._documents:
            self._documents[document_id]["status"] = status


class AppState:
    def __init__(self, object_store: ObjectStoreClient, job_queue: JobQueue):
        self.object_store = object_store
        self.job_queue = job_queue
        self.document_repo = InMemoryDocumentRepository()

    @classmethod
    async def create(cls) -> "AppState":
        return cls(ObjectStoreClient(), JobQueue())

    async def aclose(self) -> None:
        await self.job_queue.aclose()
