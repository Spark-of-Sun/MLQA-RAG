"""Ingestion service entrypoint: ``uvicorn ingestion.main:app``.

Needs: PG_DSN_INGESTION, VALKEY_URL, a KMS and the trust root, the object store (OBJECT_STORE_*),
Qdrant with the read-write key, and the embedding model (EMBEDDING_MODEL; loaded at start-up, after
every setting has been checked). Set CLAMD_HOST to add the ClamAV daemon to the always-on checks.
"""

from __future__ import annotations

from ingestion.app import create_app
from ingestion.chunker import ChunkConfig, HfTokenizer
from ingestion.embedder import Embedder, EmbeddingConfig
from ingestion.pipeline import Components, IngestionPipeline
from ingestion.scanner import ClamdScanner, CompositeScanner, Scanner, StaticChecks
from lmqa_auth.runtime import (
    context_verifier,
    database,
    env,
    key_provider,
    optional_env,
    valkey_client,
)
from lmqa_keys import KeyService
from lmqa_objectstore import ObjectStore
from lmqa_vectorstore import VectorWriter


def build() -> IngestionPipeline:
    """Construct the pipeline. Settings are validated first; models load last."""
    db, keys = database("INGESTION"), KeyService(key_provider())
    objects = ObjectStore(
        optional_env("OBJECT_STORE_ENDPOINT"),
        env("OBJECT_STORE_CREDS_INGESTION_ACCESS_KEY"),
        env("OBJECT_STORE_CREDS_INGESTION_SECRET_KEY"),
        env("OBJECT_STORE_BUCKET"),
        env("OBJECT_STORE_REGION", "us-east-1"),
    )
    collection = f"{env('QDRANT_COLLECTION_PREFIX', 'chunks')}_v1"
    vectors = VectorWriter(env("QDRANT_URL"), env("QDRANT_KEY_RW"), collection)
    scanners: list[Scanner] = [StaticChecks()]
    if clamd := optional_env("CLAMD_HOST"):
        scanners.append(ClamdScanner(clamd, int(env("CLAMD_PORT", "3310"))))
    embedding = EmbeddingConfig(dense_model=env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    return IngestionPipeline(
        Components(
            db=db,
            keys=keys,
            objects=objects,
            vectors=vectors,
            embedder=Embedder(embedding),
            scanner=CompositeScanner(*scanners),
            tokenizer=HfTokenizer(embedding.dense_model),
            chunk_config=ChunkConfig.for_embedding(embedding.max_sequence),
        )
    )


_pipeline = build()
app = create_app(_pipeline, context_verifier("ingestion", valkey_client("INGESTION")))
