"""Unit and property tests of the section 5.4 oracle."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lmqa_models import AccessContext, Document, Grant, Role, Visibility, decide

pytestmark = [pytest.mark.unit, pytest.mark.stage1]

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
ME, OTHER, MATTER = uuid4(), uuid4(), uuid4()


def ctx(role: Role = Role.TENANT, **kw: object) -> AccessContext:
    return AccessContext(user_id=ME, role=role, now=NOW, **kw)  # type: ignore[arg-type]


def doc(**kw: object) -> Document:
    base = {"owner_user_id": OTHER, "visibility": Visibility.MATTER, "tier": 2, "matter_id": MATTER}
    return Document(**{**base, **kw})  # type: ignore[arg-type]


def test_def02_tenant_cannot_read_others_private_doc_inside_granted_matter() -> None:
    c = ctx(grants={MATTER: Grant(max_tier=4)})
    assert not decide(c, doc(visibility=Visibility.PRIVATE)).allow


def test_grant_allows_matter_doc_up_to_tier_ceiling() -> None:
    c = ctx(grants={MATTER: Grant(max_tier=2)})
    assert decide(c, doc(tier=2)).allow
    assert not decide(c, doc(tier=3)).allow


def test_expired_grant_denies() -> None:
    c = ctx(grants={MATTER: Grant(max_tier=4, expires_at=NOW - timedelta(seconds=1))})
    assert not decide(c, doc()).allow


def test_wall_beats_grant_and_ownership() -> None:
    c = ctx(walls=frozenset({MATTER}), grants={MATTER: Grant(max_tier=4)})
    assert not decide(c, doc()).allow
    assert not decide(c, doc(owner_user_id=ME)).allow
    assert decide(c, doc(owner_user_id=ME)).rule == 2


def test_wall_beats_admin_role_and_emergency() -> None:
    admin = ctx(Role.ADMIN, walls=frozenset({MATTER}))
    assert not decide(admin, doc()).allow
    em = ctx(walls=frozenset({MATTER}), emergency={MATTER: NOW + timedelta(minutes=30)})
    assert not decide(em, doc()).allow


def test_owner_reads_own_private_document() -> None:
    assert decide(ctx(), doc(owner_user_id=ME, visibility=Visibility.PRIVATE, matter_id=None)).allow


def test_admin_reads_matter_docs_all_tiers_but_not_private_by_default() -> None:
    admin = ctx(Role.ADMIN)
    assert decide(admin, doc(tier=4)).allow
    assert not decide(admin, doc(visibility=Visibility.PRIVATE)).allow


def test_break_glass_requires_flag_and_session() -> None:
    private = doc(visibility=Visibility.PRIVATE)
    assert not decide(ctx(Role.ADMIN, admin_can_read_private=True), private).allow
    assert not decide(ctx(Role.ADMIN, break_glass_active=True), private).allow
    both = decide(ctx(Role.ADMIN, admin_can_read_private=True, break_glass_active=True), private)
    assert both.allow
    assert both.read_only


def test_emergency_is_tier_capped_and_expires() -> None:
    c = ctx(emergency={MATTER: NOW + timedelta(minutes=5)})
    assert decide(c, doc(tier=3)).allow
    assert decide(c, doc(tier=3)).read_only
    assert not decide(c, doc(tier=4)).allow
    gone = ctx(emergency={MATTER: NOW - timedelta(seconds=1)})
    assert not decide(gone, doc(tier=1)).allow


@pytest.mark.parametrize("flag", ["membership_active", "workspace_active", "org_active"])
def test_any_inactive_layer_denies_everything(flag: str) -> None:
    c = ctx(Role.ADMIN, **{flag: False})
    assert decide(c, doc(owner_user_id=ME)).rule == 1
    assert not decide(c, doc(owner_user_id=ME)).allow


def test_super_admin_never_reads_content() -> None:
    sa = ctx(Role.SUPER_ADMIN, grants={MATTER: Grant(max_tier=4)})
    assert not decide(sa, doc(owner_user_id=ME)).allow


uuids = st.sampled_from([uuid4() for _ in range(4)])


@st.composite
def scenarios(draw: st.DrawFn) -> tuple[AccessContext, Document]:
    matters = [uuid4() for _ in range(3)]
    users = [uuid4() for _ in range(3)]
    me = users[0]
    walls = frozenset(draw(st.lists(st.sampled_from(matters), max_size=2)))
    grants = {
        m: Grant(max_tier=draw(st.integers(1, 4)))
        for m in draw(st.lists(st.sampled_from(matters), max_size=3, unique=True))
    }
    emergency = {
        m: NOW + timedelta(minutes=draw(st.integers(-5, 60)))
        for m in draw(st.lists(st.sampled_from(matters), max_size=2, unique=True))
    }
    c = AccessContext(
        user_id=me,
        role=draw(st.sampled_from([Role.ADMIN, Role.TENANT])),
        now=NOW,
        membership_active=draw(st.booleans()),
        walls=walls,
        grants=grants,
        emergency=emergency,
        admin_can_read_private=draw(st.booleans()),
        break_glass_active=draw(st.booleans()),
    )
    vis = draw(st.sampled_from(list(Visibility)))
    d = Document(
        owner_user_id=draw(st.sampled_from(users)),
        visibility=vis,
        tier=draw(st.integers(1, 4)),
        matter_id=draw(st.sampled_from(matters)) if vis is Visibility.MATTER else None,
    )
    return c, d


@given(scenarios())
def test_property_wall_always_wins(scenario: tuple[AccessContext, Document]) -> None:
    c, d = scenario
    if c.membership_active and d.matter_id in c.walls:
        assert not decide(c, d).allow


@given(scenarios())
def test_property_tier_four_is_never_reached_by_emergency(
    scenario: tuple[AccessContext, Document],
) -> None:
    c, d = scenario
    verdict = decide(c, d)
    if verdict.allow and verdict.rule == 6:
        assert d.tier <= 3


@given(scenarios())
def test_property_other_users_private_docs_only_via_break_glass(
    scenario: tuple[AccessContext, Document],
) -> None:
    c, d = scenario
    verdict = decide(c, d)
    if verdict.allow and d.visibility is Visibility.PRIVATE and d.owner_user_id != c.user_id:
        assert verdict.rule == 7
        assert c.role is Role.ADMIN
        assert c.admin_can_read_private
        assert c.break_glass_active


def test_unknown_uuid_type_is_uuid() -> None:
    assert isinstance(ME, UUID)
