"""G5.1: the filter builder and the shape of the vector API (doc 10.5)."""

import inspect
from uuid import uuid4

import pytest

from lmqa_vectorstore import (
    MAX_INLINE_MATTERS,
    NoFilterError,
    VectorReader,
    VectorScope,
    VectorWriter,
    build_filter,
    filter_mentions_scope,
)

pytestmark = [pytest.mark.unit, pytest.mark.stage5]


def scope(**kw: object) -> VectorScope:
    base = {"org_id": uuid4(), "workspace_id": uuid4(), "user_id": uuid4(), "role": "tenant"}
    return VectorScope(**{**base, **kw})  # type: ignore[arg-type]


def text(s: VectorScope) -> str:
    return build_filter(s).qdrant_filter.model_dump_json()


@pytest.mark.parametrize("role", ["tenant", "admin"])
def test_every_filter_pins_organization_and_workspace(role: str) -> None:
    s = scope(
        role=role,
        grants={uuid4(): 2},
        walled=frozenset({uuid4()}),
        emergency_matters=frozenset({uuid4()}),
    )
    built = build_filter(s)
    assert filter_mentions_scope(built.qdrant_filter, s)
    assert str(s.org_id) in text(s)
    assert str(s.workspace_id) in text(s)


@pytest.mark.parametrize("role", ["super_admin", "operator", "", "support", "ADMIN"])
def test_no_filter_for_a_role_without_content_access(role: str) -> None:
    with pytest.raises(NoFilterError):
        build_filter(scope(role=role))


def test_walls_become_must_not_and_apply_to_every_branch() -> None:
    walled = uuid4()
    built = build_filter(scope(walled=frozenset({walled}))).qdrant_filter
    assert built.must_not, "walled matters are excluded globally, so they also beat ownership"
    assert str(walled) in built.model_dump_json()
    assert build_filter(scope()).qdrant_filter.must_not is None


def test_a_tenant_without_grants_gets_only_their_own_documents() -> None:
    s = scope()
    body = text(s)
    assert str(s.user_id) in body
    assert '"matter"' not in body.replace('"matter_id"', "")


def test_each_grant_carries_its_own_tier_ceiling() -> None:
    m1, m2 = uuid4(), uuid4()
    body = text(scope(grants={m1: 1, m2: 3}))
    assert str(m1) in body
    assert str(m2) in body
    assert '"lte":1' in body.replace(" ", "")
    assert '"lte":3' in body.replace(" ", "")


def test_emergency_access_adds_the_matter_with_the_tier_cap_of_three() -> None:
    m = uuid4()
    body = text(scope(emergency_matters=frozenset({m}))).replace(" ", "")
    assert str(m) in body
    assert '"lte":3' in body


def test_admin_private_read_needs_the_explicit_flag() -> None:
    plain = text(scope(role="admin")).replace(" ", "")
    assert '"value":"private"' not in plain
    with_flag = text(scope(role="admin", admin_private_read=True)).replace(" ", "")
    assert '"value":"private"' in with_flag
    assert '"value":"matter"' in plain, "admins read every matter-shared document"


def test_narrowing_adds_a_constraint_and_never_widens() -> None:
    m = uuid4()
    base = build_filter(scope(grants={m: 4})).qdrant_filter
    narrowed = build_filter(scope(grants={m: 4}, narrow_to=frozenset({uuid4()}))).qdrant_filter
    assert len(narrowed.must or []) == len(base.must or []) + 1


def test_large_grant_sets_switch_to_overfetch_and_cross_check() -> None:
    many = {uuid4(): 2 for _ in range(MAX_INLINE_MATTERS + 1)}
    built = build_filter(scope(grants=many))
    assert built.overfetch
    assert len(built.qdrant_filter.model_dump_json()) < 2000, "no giant inline matter list"
    assert not build_filter(scope(grants={uuid4(): 2})).overfetch
    assert not build_filter(scope(role="admin")).overfetch


def test_the_reader_has_one_query_method_and_it_requires_a_scope() -> None:
    public = [
        n for n, _ in inspect.getmembers(VectorReader, inspect.isfunction) if not n.startswith("_")
    ]
    assert sorted(public) == ["aclose", "search"]
    params = list(inspect.signature(VectorReader.search).parameters)
    assert params[1] == "scope"
    assert inspect.signature(VectorReader.search).parameters["scope"].annotation in {
        "VectorScope",
        VectorScope,
    }


def test_every_destructive_writer_call_requires_organization_and_workspace() -> None:
    for name in ("delete_document", "delete_workspace", "set_access_payload", "list_points"):
        params = inspect.signature(getattr(VectorWriter, name)).parameters
        assert {"org_id", "workspace_id"} <= set(params), name
    public = {
        n for n, _ in inspect.getmembers(VectorWriter, inspect.isfunction) if not n.startswith("_")
    }
    assert not any("filter" in n or "raw" in n for n in public), "nothing accepts a raw filter"


@pytest.mark.parametrize("url", ["http://qdrant.internal:6333", "http://10.0.0.5:6333", "ftp://x"])
def test_an_api_key_never_crosses_plain_http_off_loopback(url: str) -> None:
    with pytest.raises(ValueError, match="https"):
        VectorReader(url, "key", "c")
    with pytest.raises(ValueError, match="https"):
        VectorWriter(url, "key", "c")
