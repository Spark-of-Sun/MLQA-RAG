"""G3.6 (drift half): the authorization matrix, the OpenAPI documents and the implementation must agree.

Every non-deferred matrix route must exist in the service that serves it, and every public route a
service implements must have an authorization decision in the matrix. A route that exists internally but
not in the matrix is unreachable from outside (the Gateway answers 404); a matrix route that no service
implements would be an allow-listed hole. Either is a failure.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.contract, pytest.mark.stage3]
ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "export_openapi", ROOT / "tools" / "export_openapi.py"
)
assert _spec
assert _spec.loader
_exporter = importlib.util.module_from_spec(_spec)
sys.modules["export_openapi"] = _exporter
_spec.loader.exec_module(_exporter)
export = _exporter.export
AUDIT_ALIASES = {
    "/v1/org/audit",
    "/v1/workspace/audit",
    "/v1/audit/me",
}  # all served by audit /events
SERVED_BY_GATEWAY = {"/v1/query", "/v1/health"}
INTERNAL_ONLY = {"/internal/v1/health", "/internal/v1/payloads/{event_id}", "/internal/v1/verify"}


def internal(path: str) -> str:
    return "/internal/v1/events" if path in AUDIT_ALIASES else "/internal" + path


@pytest.fixture(scope="module")
def docs() -> dict[str, dict]:
    return export()


@pytest.fixture(scope="module")
def routes() -> list[dict]:
    return yaml.safe_load((ROOT / "contracts/authz-matrix.yaml").read_text())["routes"]


def normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def served(docs: dict[str, dict], service: str) -> set[tuple[str, str]]:
    return {(m.upper(), normalize(p)) for p, ops in docs[service]["paths"].items() for m in ops}


def test_every_enabled_matrix_route_is_implemented_by_its_service(
    docs: dict[str, dict], routes: list[dict]
) -> None:
    missing = []
    for r in routes:
        if r.get("feature") or r["path"] in SERVED_BY_GATEWAY:
            continue
        service = r["service"]
        if (r["method"], normalize(internal(r["path"]))) not in served(docs, service):
            missing.append(f"{r['method']} {r['path']} -> {service}")
    assert missing == [], f"routes allow-listed in the matrix but not implemented: {missing}"


def test_every_public_service_route_has_an_authorization_decision(
    docs: dict[str, dict], routes: list[dict]
) -> None:
    allowed = {
        (r["method"], normalize(internal(r["path"])))
        for r in routes
        if r["path"] not in SERVED_BY_GATEWAY
    }
    unlisted = []
    for service in ("identity", "ingestion", "audit"):
        for method, path in served(docs, service):
            if normalize("/internal/v1/health") == path or path in {
                normalize(p) for p in INTERNAL_ONLY
            }:
                continue
            if (method, path) not in allowed:
                unlisted.append(f"{method} {path} ({service})")
    assert unlisted == [], (
        f"implemented but absent from the matrix, so unreachable from outside: {unlisted}"
    )


def test_every_service_document_declares_its_security_relevant_routes(
    docs: dict[str, dict],
) -> None:
    assert set(docs) == {
        "identity",
        "ingestion",
        "retrieval",
        "generation",
        "citation-validator",
        "audit",
    }
    for name, doc in docs.items():
        assert doc["openapi"].startswith("3."), name
        assert any(p.endswith("/health") for p in doc["paths"]), f"{name} has no liveness route"


def test_request_bodies_that_carry_uuid_and_datetime_fields_are_described(
    docs: dict[str, dict],
) -> None:
    """A Pydantic model whose annotation imports were moved under TYPE_CHECKING cannot build its schema."""
    schemas = docs["identity"]["components"]["schemas"]
    grant = schemas["GrantIn"]["properties"]
    assert grant["matter_id"]["format"] == "uuid"
    assert any(opt.get("format") == "date-time" for opt in grant["expires_at"]["anyOf"])
    assert "grants" in schemas["DecisionIn"]["properties"]
