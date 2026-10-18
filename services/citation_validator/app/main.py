from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.auth.service_token import ServiceAuthError, verify_internal_service_key
from common.logging import configure_logging, get_logger

from app.entailment_check import get_entailment_checker
from app.schemas.requests import ValidateRequest, ValidateResponse
from app.validator import validate_answer

configure_logging(service_name="citation_validator")
log = get_logger(__name__)

app = FastAPI(title="Legal/Medical QA — Citation Validator", version="0.1.0")


def _require_internal_auth(request: Request) -> None:
    try:
        verify_internal_service_key(request.headers.get("X-Internal-Service-Key"))
    except ServiceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/internal/v1/validate", response_model=ValidateResponse)
async def validate(body: ValidateRequest, request: Request):
    """Called only by the Gateway, after Generation returns. Deterministic,
    non-LLM — never calls an LLM, matches docs/api-contracts/
    citation-validator.yaml. This is the hard gate before any answer
    reaches the user.
    """
    _require_internal_auth(request)
    entailment_checker = get_entailment_checker()

    result = validate_answer(
        answer_text=body.answer_text,
        retrieved_chunks=body.retrieved_chunks,
        tenant_policy=body.tenant_policy,
        entailment_support_threshold=body.entailment_support_threshold,
        entailment_checker=entailment_checker,
    )

    if result.validation_outcome.value != "pass":
        log.info(
            "citation_validation_non_pass",
            outcome=result.validation_outcome.value,
            finding_count=len(result.findings),
        )

    return result


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
