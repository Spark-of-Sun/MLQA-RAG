"""G0.10 / G3.6 (model-free half): the authorization matrix and feature flags validate against a schema."""

from pathlib import Path

import pytest
import yaml

from gateway.matrix import Matrix

pytestmark = [pytest.mark.contract, pytest.mark.stage3]
ROOT = Path(__file__).resolve().parents[2]
ROLES = {"SA", "AD", "TE", "ON", "PENDING", "ANON"}
SERVICES = {
    "gateway",
    "identity",
    "ingestion",
    "audit",
    "retrieval",
    "generation",
    "citation_validator",
    "ops",
}
AUDIENCES = {"main", "onboarding"}


@pytest.fixture(scope="module")
def raw() -> list[dict]:
    return yaml.safe_load((ROOT / "contracts/authz-matrix.yaml").read_text())["routes"]


def test_every_role_is_a_string_from_the_known_set_never_a_yaml_boolean(raw: list[dict]) -> None:
    for route in raw:
        assert route["roles"], route
        for role in route["roles"]:
            assert isinstance(role, str), (
                f"{route['path']}: role {role!r} is not a string (unquoted ON/NO/YES is a boolean)"
            )
            assert role in ROLES, f"{route['path']}: unknown role {role!r}"


def test_every_route_declares_known_service_audience_and_booleans(raw: list[dict]) -> None:
    seen = set()
    for r in raw:
        assert r["service"] in SERVICES
        assert r["audience"] in AUDIENCES
        assert all(isinstance(r[k], bool) for k in ("step_up", "state_changing", "stream"))
        assert r["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert r["path"].startswith("/v1/")
        key = (r["method"], r["path"])
        assert key not in seen, f"duplicate route {key}"
        seen.add(key)


def test_state_changing_methods_are_marked_and_reads_are_not(raw: list[dict]) -> None:
    for r in raw:
        if r["path"] == "/v1/query":
            continue  # a streamed POST that only reads
        assert r["state_changing"] == (r["method"] != "GET"), r["path"]


def test_a_super_admin_has_no_route_to_content_or_tenants(raw: list[dict]) -> None:
    for r in raw:
        if "SA" in r["roles"]:
            assert not r["path"].startswith(
                ("/v1/documents", "/v1/query", "/v1/workspace/tenants", "/v1/workspace/walls")
            ), r
            assert r["path"] != "/v1/workspace/audit"


def test_onboarding_routes_accept_only_the_onboarding_audience_and_nothing_else_does(
    raw: list[dict],
) -> None:
    for r in raw:
        assert (r["audience"] == "onboarding") == (r["roles"] == ["ON"]), r["path"]


def test_privileged_actions_require_step_up(raw: list[dict]) -> None:
    must = {
        ("POST", "/v1/org/code"),
        ("POST", "/v1/org/code/rotate"),
        ("POST", "/v1/workspace/code"),
        ("POST", "/v1/workspace/code/rotate"),
        ("POST", "/v1/org/admins/{id}/approve"),
        ("POST", "/v1/org/admins/{id}/suspend"),
        ("PATCH", "/v1/workspace/policy"),
    }
    got = {(r["method"], r["path"]) for r in raw if r["step_up"]}
    assert must <= got


def test_the_matcher_loads_and_disabled_features_answer_as_if_absent() -> None:
    m = Matrix.load(ROOT / "contracts/authz-matrix.yaml", ROOT / "contracts/features.toml")
    onboarding = m.match("POST", "/v1/onboarding/organization")
    assert onboarding is not None
    assert m.allows(onboarding, "ON")
    assert not m.allows(onboarding, "SA")
    assert m.match("POST", "/v1/governance-requests") is None, "disabled feature: 404"
    assert m.match("GET", "/v1/org/admins/123") is not None
    assert m.match("DELETE", "/v1/org") is None
