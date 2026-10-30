"""Retrieval service entrypoint: ``uvicorn retrieval.main:app``.

Needs: PG_DSN_RETRIEVAL, VALKEY_URL, a KMS and the trust root,
Qdrant with the READ-ONLY key, and the
embedding and re-ranking models (loaded at start-up). The retrieval relevance threshold is an
uncalibrated placeholder until the Stage 5 calibration on labelled data (G5.3, G5.11) is done.
"""

from __future__ import annotations

import logging
import os

from lmqa_auth.runtime import context_verifier, database, env, key_provider, valkey_client
from lmqa_keys import KeyService
from lmqa_vectorstore import VectorReader
from retrieval.app import create_app
from retrieval.search import DEFAULT_THRESHOLD, QueryModels, Retriever

LOG = logging.getLogger("retrieval")
_threshold = float(env("RERANK_THRESHOLD", str(DEFAULT_THRESHOLD)))
if "RERANK_THRESHOLD" not in os.environ:
    LOG.warning("RERANK_THRESHOLD is not set: using the UNCALIBRATED default %s", _threshold)

_retriever = Retriever(
    database("RETRIEVAL"),
    KeyService(key_provider()),
    VectorReader(
        env("QDRANT_URL"), env("QDRANT_KEY_RO"), f"{env('QDRANT_COLLECTION_PREFIX', 'chunks')}_v1"
    ),
    QueryModels(
        env("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        reranker=env("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"),
    ),
    threshold=_threshold,
)
app = create_app(_retriever, context_verifier("retrieval", valkey_client("RETRIEVAL")))
