"""Frozen MVP-only features (task 3.6, DEV-21, KD-13, pending Q-04 and Q-39; R-4.1, R-39).

Each feature sits behind a flag in contracts/features.toml that is off and cannot be enabled while its questions are
open. While off: its gateway routes answer 404 exactly like a path with no route, its request fields are refused,
nothing is sent to an LLM for it, its background state (the quota counter file) is not written, and it adds no allow
path to any read (no share or `workspace` document can be created, and the audit view does not widen for them).

Flags are switched through the documented local override (FEATURE_<NAME> with APP_ENV=local), never by patching.
"""

from __future__ import annotations

import logging
import re
import tomllib
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from audit.service import AuditService
from gateway import frozen
from gateway.app import create_app
from generation import GenerationService, Turn
from generation.rerank import LLMReranker
from ingestion.documents import upload_visibility
from lmqa_models.contracts import features
from lmqa_models.envfile import ROOT
from lmqa_models.errors import BadRequest, NotFound
from lmqa_models.principal import Membership, Principal
from lmqa_models.settings import LLM_RERANK, Settings, load_settings
from lmqa_testing.tools import load_tool

pytestmark = [pytest.mark.stage1]

FROZEN = (
    "chats",
    "profiles",
    "named_shares",
    "workspace_visibility",
    "usage_counts",
    "public_site",
    "llm_reranker",
    "quota_rotation",
)
SPEC = tomllib.loads((ROOT / "contracts" / "features.toml").read_text(encoding="utf-8"))["feature"]
MATRIX = yaml.safe_load((ROOT / "contracts" / "authz-matrix.yaml").read_text(encoding="utf-8"))[
    "routes"
]

SetFlags = Callable[..., None]


@pytest.fixture
def flags(monkeypatch: pytest.MonkeyPatch) -> Iterator[SetFlags]:
    """Every frozen flag off (whatever a local .env says) unless the test turns it on."""

    def set_flags(app_env: str = "local", **on: bool) -> None:
        monkeypatch.setenv("APP_ENV", app_env)
        for name in FROZEN:
            monkeypatch.setenv(f"FEATURE_{name.upper()}", "on" if on.get(name) else "off")
        features.cache_clear()

    set_flags()
    yield set_flags
    features.cache_clear()


def _tenant() -> Principal:
    m = Membership(
        "m-1", "tenant", "active", "org-1", "Org", "legal", "active", "ws-1", "WS", "active"
    )
    return Principal("u-1", "auth0|u-1", "t@example.test", "T", m)


# --- the contract ------------------------------------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.parametrize("name", FROZEN)
def test_frozen_feature_is_declared_off_bound_and_pending(name: str) -> None:
    spec = SPEC[name]
    assert spec["enabled"] is False
    assert "Q-04" in spec["pending"]
    assert spec["gates"]
    assert all(re.fullmatch(r"G\d+\.\d+", g) for g in spec["gates"])
    if name == "chats":
        assert "Q-39" in spec["pending"]


@pytest.mark.contract
def test_matrix_flags_are_declared_and_frozen_routes_carry_theirs() -> None:
    for route in MATRIX:
        assert route.get("feature") is None or route["feature"] in SPEC, route
    gated = {(r["method"], r["path"]): r.get("feature") for r in MATRIX}
    assert gated[("GET", "/v1/profile")] == gated[("PATCH", "/v1/profile")] == "profiles"
    chats = [k for k in gated if k[1].startswith("/v1/conversations")]
    assert len(chats) == 4
    assert all(gated[k] == "chats" for k in chats)


@pytest.mark.unit
def test_gatekeeper_rejects_an_enabled_frozen_flag_whatever_the_attestations() -> None:
    gatekeeper = load_tool("gatekeeper")
    enabled = {"chats": {"gates": ["G6.4"], "pending": ["Q-04", "Q-39"], "enabled": True}}
    assert gatekeeper.feature_problems(enabled) == ["chats: enabled but frozen pending Q-04, Q-39"]
    assert gatekeeper.feature_problems({"chats": {**enabled["chats"], "enabled": False}}) == []
    assert gatekeeper.feature_problems({"x": {"gates": ["G1.1"], "enabled": True}}) == []


@pytest.mark.contract
def test_gatekeeper_features_command_fails_on_an_enabled_frozen_flag(tmp_path: Path) -> None:
    path = tmp_path / "features.toml"
    path.write_text(
        '[feature.chats]\ngates = ["G5.3"]\npending = ["Q-04", "Q-39"]\nenabled = true\n',
        encoding="utf-8",
    )
    gatekeeper = load_tool("gatekeeper")
    assert gatekeeper.check_features(path) == 1
    assert gatekeeper.check_features() == 0  # the committed file: every flag off


@pytest.mark.contract
def test_a_frozen_flag_honours_the_override_only_in_local(flags: SetFlags) -> None:
    flags("staging", chats=True)
    assert features()["chats"] is False
    flags("production", chats=True)
    assert features()["chats"] is False
    flags("local", chats=True)
    assert features()["chats"] is True


# --- routes: 404 like a missing path, before authentication ------------------------------------------------------


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


@pytest.mark.contract
@pytest.mark.asyncio
async def test_frozen_routes_answer_404_exactly_like_a_missing_route(flags: SetFlags) -> None:
    app = create_app(load_settings(), resume_jobs=False)
    frozen_routes = [r for r in MATRIX if r.get("feature") in FROZEN]
    assert len(frozen_routes) == 6
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gw"
    ) as client:
        missing = await client.get("/v1/no-such-route")
        assert missing.status_code == 404
        for r in frozen_routes:
            resp = await client.request(r["method"], _concrete(r["path"]), json={})
            assert (resp.status_code, resp.json()) == (404, missing.json()), r
        # A listed, unflagged route reaches authentication instead.
        assert (await client.get("/v1/workspace/members")).status_code == 401
        flags(chats=True, profiles=True)
        assert (await client.get("/v1/conversations")).status_code == 401
        assert (await client.patch("/v1/profile", json={})).status_code == 401


@pytest.mark.contract
def test_a_question_naming_a_chat_is_404_while_chats_is_off(flags: SetFlags) -> None:
    app = create_app(load_settings(), resume_jobs=False)
    with pytest.raises(NotFound):
        app.state.services.queries.ask(_tenant(), "What does section 302 say?", str(uuid.uuid4()))


# --- nothing goes to an LLM for a frozen feature -----------------------------------------------------------------


@pytest.mark.contract
def test_query_planning_calls_no_model_while_chats_is_off(
    flags: SetFlags, caplog: pytest.LogCaptureFixture
) -> None:
    gen = GenerationService(
        Settings(llm_model="gemini-2.5-flash")
    )  # no key: any call fails and is logged
    history = [Turn("What does section 302 say?", "It defines murder.")]
    with caplog.at_level(logging.WARNING, logger="generation.service"):
        plan = gen.plan_query(history, "and section 304?", expand=True)
    assert (plan.question, plan.alternatives, plan.tokens_in, plan.model) == (
        "and section 304?",
        [],
        0,
        "",
    )
    assert "query planning unavailable" not in caplog.text
    flags(chats=True)
    with caplog.at_level(logging.WARNING, logger="generation.service"):
        gen.plan_query(history, "and section 304?", expand=True)
    assert (
        "query planning unavailable" in caplog.text
    )  # with the flag on, the planner was really called


@pytest.mark.contract
def test_llm_reranker_is_not_built_while_frozen(flags: SetFlags) -> None:
    settings = replace(Settings(), rerank_model=LLM_RERANK)
    assert GenerationService(settings).reranker is None
    flags(llm_reranker=True)
    assert isinstance(GenerationService(settings).reranker, LLMReranker)


@pytest.mark.contract
def test_quota_rotation_off_uses_the_primary_key_and_writes_no_counter(
    flags: SetFlags, tmp_path: Path
) -> None:
    counter = tmp_path / "quota.json"
    s = Settings(gemini_api_key="key-1", gemini_api_keys=("key-1", "key-2"), quota_file=counter)
    assert [k for _, k in s.gemini_keys()] == ["key-1"]
    assert s.quota() is None
    assert not counter.exists()
    flags(quota_rotation=True)
    assert [k for _, k in s.gemini_keys()] == ["key-1", "key-2"]
    tracker = s.quota()
    assert tracker is not None
    tracker.next_question()
    assert counter.is_file()


# --- no allow path to a read --------------------------------------------------------------------------------------


@pytest.mark.contract
def test_uploads_cannot_create_a_share_or_a_workspace_document(flags: SetFlags) -> None:
    assert upload_visibility("admin", None, []) == "private"
    assert upload_visibility("tenant", "private", ["", " "]) == "private"
    with pytest.raises(BadRequest):
        upload_visibility("admin", "workspace", [])
    with pytest.raises(BadRequest):
        upload_visibility("tenant", None, ["admin"])
    with pytest.raises(BadRequest):
        upload_visibility("admin", "private", [str(uuid.uuid4())])
    flags(workspace_visibility=True, named_shares=True)
    assert upload_visibility("admin", None, []) == "workspace"
    assert upload_visibility("tenant", None, ["admin"]) == "private"


def _placeholders(sql: str) -> int:
    return len(re.findall(r"(?<!%)%s", sql))


@pytest.mark.contract
def test_tenant_audit_view_gains_nothing_from_shares_or_workspace_documents(
    flags: SetFlags,
) -> None:
    p = _tenant()
    for build in (AuditService._scope, AuditService._title_visible):
        sql, args = build(p)
        assert "shared_with" not in sql
        assert "'workspace'" not in sql
        assert _placeholders(sql) == len(args)
    flags(workspace_visibility=True, named_shares=True)
    for build in (AuditService._scope, AuditService._title_visible):
        sql, args = build(p)
        assert "shared_with" in sql
        assert "'workspace'" in sql
        assert _placeholders(sql) == len(args)


# --- response fields of frozen features ---------------------------------------------------------------------------

MEMBER: dict[str, Any] = {
    "id": "m-1",
    "status": "active",
    "email": "t@example.test",
    "job_title": "Paralegal",
    "department": "Litigation",
    "phone": "+1 555",
    "profile_updated_at": None,
    "documents": 3,
    "private_documents": 1,
    "shared_with_you": 1,
    "shared_with_them": 0,
    "shared_with_workspace": 2,
    "questions": 7,
    "tokens": 900,
    "last_question_at": None,
}
ADMIN: dict[str, Any] = {
    "id": "a-1",
    "tenants": 2,
    "tenants_pending": 1,
    "documents": 4,
    "queries_30d": 9,
}


@pytest.mark.contract
def test_member_and_admin_rows_carry_no_profile_or_usage_fields_while_frozen(
    flags: SetFlags,
) -> None:
    assert frozen.member_rows([MEMBER]) == [
        {"id": "m-1", "status": "active", "email": "t@example.test"}
    ]
    assert frozen.admin_rows([ADMIN]) == [{"id": "a-1", "tenants": 2, "tenants_pending": 1}]
    flags(profiles=True)
    assert set(frozen.member_rows([MEMBER])[0]) == {"id", "status", "email"} | frozen.PROFILE_FIELDS
    flags(profiles=True, usage_counts=True)
    assert frozen.member_rows([MEMBER]) == [MEMBER]
    assert frozen.admin_rows([ADMIN]) == [ADMIN]
