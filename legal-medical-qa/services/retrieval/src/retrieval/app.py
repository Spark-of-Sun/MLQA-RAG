"""The retrieval HTTP API (doc 15.9): ``POST /internal/v1/search``.

Retrieval hands off through the retrieval ledger in PostgreSQL, so the response carries only the
request ID and counts. Chunk text never travels through the Gateway. The request ID that is
recorded is the one inside the verified context token.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lmqa_auth import ContextClaims, ContextVerifier
from lmqa_auth.web import context_claims, problem
from lmqa_vectorstore import NoFilterError
from retrieval.search import NoAccessError, RetrievalUnavailableError, Retriever

Claims = Annotated[ContextClaims, Depends(context_claims())]


class SearchIn(BaseModel):
    """A question, optionally narrowed to matters the caller can already read."""

    question: str = Field(min_length=1, max_length=2000)
    matter_ids: list[UUID] | None = None


def create_app(retriever: Retriever, verifier: ContextVerifier) -> FastAPI:
    """Build the app around a constructed retriever and this service's own token verifier."""
    app = FastAPI(title="retrieval", docs_url=None, redoc_url=None)
    app.state.verifier = verifier

    @app.get("/internal/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/v1/search", response_model=None)
    async def search(body: SearchIn, claims: Claims) -> dict[str, object] | JSONResponse:
        narrow = frozenset(body.matter_ids) if body.matter_ids else None
        try:
            result = await retriever.retrieve(
                claims.db_context(), body.question, narrow_to=narrow, request_id=claims.request_id
            )
        except NoAccessError, NoFilterError:
            return problem(403, "Forbidden")  # a system-level refusal; never an unfiltered search
        except RetrievalUnavailableError:
            return problem(503, "Retrieval unavailable")  # no fallback scan of PostgreSQL
        return {
            "request_id": str(result.request_id),
            "kept": len(result.chunks),
            "candidates": result.candidates,
            "dropped": len(result.dropped),
            "mismatches": result.mismatches,
            "overfetch": result.overfetch,
        }

    return app
