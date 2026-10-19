"""Local, no-Docker, no-Redis smoke test for the Ingestion pipeline's real
function code (OCR -> chunk -> embed -> vector store), using the fake OCR
and embedding backends (no tesseract/torch required). Bypasses the FastAPI
app, the Arq job queue, and Redis entirely -- this calls
app.workers.tasks.process_document() directly, the same function the real
Arq worker (app/workers/tasks.py:ingest_document) calls in production.

This proves the chunking/embedding/vector-store code actually runs against
a real file's bytes, not just the fixtures baked into each unit test. It
is NOT a substitute for the real OCR/embedding backends or for a real
docker compose run -- it still uses FakeOcrBackend (no real OCR) and
FakeEmbeddingBackend (no real model).

Usage:
    python run_local_ingest.py --file sample_contract.txt \
        --document-id smith-contract-001 \
        --tenant-id t1 --matter-or-patient-id matter-1 \
        --confidentiality-tier standard --industry legal \
        --out-seed-file ../retrieval/seed_chunks.json
"""
from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-value-32-bytes-long!!")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "test-encryption-key")
os.environ.setdefault("INTERNAL_SERVICE_API_KEY", "test-internal-key")
os.environ.setdefault("ENVIRONMENT", "local")

from common.models import ConfidentialityTier, TenantIndustry

from app.embedding.fake_backend import FakeEmbeddingBackend
from app.ocr.fake_backend import FakeOcrBackend
from app.workers.tasks import process_document
from app.workers.vector_store import InMemoryVectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to a .txt file to ingest")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--matter-or-patient-id", required=True)
    parser.add_argument("--confidentiality-tier", default="standard", choices=["standard", "privileged", "phi"])
    parser.add_argument("--industry", default="legal", choices=["legal", "medical"])
    parser.add_argument("--out-seed-file", default=None, help="If set, writes the resulting chunks as Retrieval seed JSON")
    args = parser.parse_args()

    with open(args.file, "rb") as f:
        file_bytes = f.read()

    vector_store = InMemoryVectorStore()
    result = process_document(
        document_id=args.document_id,
        tenant_id=args.tenant_id,
        matter_or_patient_id=args.matter_or_patient_id,
        confidentiality_tier=ConfidentialityTier(args.confidentiality_tier),
        industry=TenantIndustry(args.industry),
        file_bytes=file_bytes,
        filename=os.path.basename(args.file),
        ocr_backend=FakeOcrBackend(),
        embedding_backend=FakeEmbeddingBackend(dimension=32),
        vector_store=vector_store,
    )

    print(f"document_id:   {result['document_id']}")
    print(f"chunk_count:   {result['chunk_count']}")
    print(f"flagged_pages: {result['flagged_pages']}")
    print(f"vector_store entries: {vector_store.count()}")
    print()

    chunks = sorted(vector_store.all_chunks(), key=lambda c: (c.page, c.section or ""))

    print("--- chunks produced ---")
    for c in chunks:
        print(f"[{c.chunk_id[:8]}] page={c.page} section={c.section!r}")
        print(f"    {c.text[:100]!r}")

    if args.out_seed_file:
        seed_data = [
            json.loads(c.model_dump_json(exclude={"dense_score", "sparse_score", "rerank_score", "created_at"}))
            for c in chunks
        ]
        with open(args.out_seed_file, "w") as f:
            json.dump(seed_data, f, indent=2)
        print(f"\nWrote {len(seed_data)} chunks to {args.out_seed_file}")
        print("Restart the Retrieval terminal (Ctrl+C, then re-run uvicorn) to pick these up.")


if __name__ == "__main__":
    main()
