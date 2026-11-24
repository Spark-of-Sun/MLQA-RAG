# ruff: noqa: INP001 - pytest runs with --import-mode=importlib; tests/ needs no package marker
"""Unit tests for the §5.4 access oracle (R-4.1): one example per rule, rule-order precedence, and smoke checks that the
shared strategies produce well-formed data."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings

from lmqa_testing import strategies as s
from lmqa_testing.oracle import Document, Principal, World, can_read, decide

pytestmark = [pytest.mark.unit, pytest.mark.stage1]

NOW = datetime(2026, 3, 1, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
EARLIER = NOW - timedelta(hours=1)
WS, MATTER = "ws-1", "m-1"
ADMIN = Principal("admin-1", "admin", WS, True, True, True, "medical")
TENANT = Principal("tenant-1", "tenant", WS, True, True, True, "medical")
MATTER_DOC = Document("d-1", WS, "someone-else", "matter", MATTER, 2)
PRIVATE_DOC = Document("d-2", WS, "someone-else", "private", None, 2)


def world(**kw: object) -> World:
    return World(now=NOW, **kw)  # type: ignore[arg-type]


# --- one example per rule ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "principal",
    [
        replace(TENANT, membership_active=False),
        replace(TENANT, workspace_active=False),
        replace(TENANT, org_active=False),
        replace(TENANT, workspace_id="ws-other"),
        Principal("sa-1", "super_admin", None, True, True, True),
        Principal("op-1", "operator", None, True, True, True),
    ],
)
def test_rule_1_inactive_or_out_of_scope_denies(principal: Principal) -> None:
    doc = replace(MATTER_DOC, owner_id=principal.user_id)
    assert decide(world(), principal, doc) == (1, False)


def test_rule_2_wall_denies() -> None:
    w = world(walls={(TENANT.user_id, MATTER)}, grants={(TENANT.user_id, MATTER): (4, None)})
    assert decide(w, TENANT, MATTER_DOC) == (2, False)


def test_rule_3_owner_allows_private_document_and_export() -> None:
    doc = replace(PRIVATE_DOC, owner_id=TENANT.user_id, tier=4)
    assert decide(world(), TENANT, doc, "export") == (3, True)


@pytest.mark.parametrize("tier", [1, 2, 3, 4])
def test_rule_4_admin_reads_matter_documents_at_every_tier(tier: int) -> None:
    assert decide(world(), ADMIN, replace(MATTER_DOC, tier=tier), "export") == (4, True)


def test_rule_5_unexpired_grant_covering_tier_allows() -> None:
    w = world(grants={(TENANT.user_id, MATTER): (2, LATER)})
    assert decide(w, TENANT, MATTER_DOC) == (5, True)
    assert decide(w, TENANT, MATTER_DOC, "export") == (5, True)


@pytest.mark.parametrize("grant", [(1, LATER), (4, EARLIER), (4, NOW)])
def test_rule_5_low_or_expired_grant_falls_through_to_deny(grant: tuple[int, datetime]) -> None:
    w = world(grants={(TENANT.user_id, MATTER): grant})
    assert decide(w, TENANT, MATTER_DOC) == (8, False)


def test_rule_6_emergency_allows_read_and_query_not_export() -> None:
    w = world(emergency={(TENANT.user_id, MATTER): (3, LATER)}, emergency_enabled={WS: True})
    assert decide(w, TENANT, MATTER_DOC, "read") == (6, True)
    assert decide(w, TENANT, MATTER_DOC, "query") == (6, True)
    assert not can_read(w, TENANT, MATTER_DOC, "export")


@pytest.mark.parametrize(
    ("principal", "doc", "cap", "enabled"),
    [
        (replace(TENANT, org_kind="legal"), MATTER_DOC, 3, True),  # legal deployment
        (TENANT, replace(MATTER_DOC, tier=4), 4, True),  # tier 4 never reachable by emergency
        (TENANT, replace(MATTER_DOC, tier=3), 2, True),  # above the cap
        (TENANT, MATTER_DOC, 3, False),  # workspace emergency_access off
    ],
)
def test_rule_6_does_not_match_outside_its_conditions(
    principal: Principal, doc: Document, cap: int, enabled: bool
) -> None:
    w = world(
        emergency={(principal.user_id, MATTER): (cap, LATER)}, emergency_enabled={WS: enabled}
    )
    assert decide(w, principal, doc) == (8, False)


def test_rule_7_break_glass_allows_read_and_query_not_export() -> None:
    w = world(break_glass={ADMIN.user_id: LATER}, admin_can_read_private={WS: True})
    assert decide(w, ADMIN, PRIVATE_DOC, "query") == (7, True)
    assert decide(w, ADMIN, PRIVATE_DOC, "export") == (7, False)


@pytest.mark.parametrize(("flag", "session"), [(False, LATER), (True, EARLIER), (True, None)])
def test_rule_7_needs_flag_and_live_session(flag: bool, session: datetime | None) -> None:
    w = world(
        break_glass={ADMIN.user_id: session} if session else {}, admin_can_read_private={WS: flag}
    )
    assert decide(w, ADMIN, PRIVATE_DOC) == (8, False)


@pytest.mark.parametrize(
    ("principal", "doc"),
    [
        (TENANT, PRIVATE_DOC),  # someone else's private document
        (TENANT, MATTER_DOC),  # no grant, no exception
        (TENANT, replace(MATTER_DOC, visibility="workspace")),  # MVP rule 7a is gone
        (ADMIN, replace(MATTER_DOC, visibility="workspace")),
    ],
)
def test_rule_8_everything_else_denies(principal: Principal, doc: Document) -> None:
    assert decide(world(), principal, doc) == (8, False)


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown operation"):
        can_read(world(), TENANT, MATTER_DOC, "delete")


# --- rule order: the first matching rule decides ---------------------------------------------------------------


def test_wall_beats_ownership() -> None:
    doc = replace(MATTER_DOC, owner_id=TENANT.user_id)
    assert decide(world(walls={(TENANT.user_id, MATTER)}), TENANT, doc) == (2, False)


def test_wall_beats_admin_matter_access() -> None:
    assert decide(world(walls={(ADMIN.user_id, MATTER)}), ADMIN, MATTER_DOC) == (2, False)


def test_inactive_membership_beats_ownership() -> None:
    doc = replace(PRIVATE_DOC, owner_id=TENANT.user_id)
    assert decide(world(), replace(TENANT, membership_active=False), doc) == (1, False)


def test_grant_beats_emergency_so_export_stays_allowed() -> None:
    key = (TENANT.user_id, MATTER)
    w = world(grants={key: (4, None)}, emergency={key: (3, LATER)}, emergency_enabled={WS: True})
    assert decide(w, TENANT, MATTER_DOC, "export") == (5, True)


# --- strategy smoke checks ---------------------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(s.scenarios())
def test_scenarios_are_well_formed(scenario: tuple[World, Principal, Document, str]) -> None:
    w, p, d, op = scenario
    assert p in w.principals and d in w.documents and op in {"read", "query", "export"}
    assert all(doc.matter_id for doc in w.documents if doc.visibility == "matter")
    assert {"super_admin", "operator"} <= {x.role for x in w.principals}
    assert isinstance(can_read(w, p, d, op), bool)


@settings(max_examples=50)
@given(s.codes("org"), s.codes("admin"), s.corrupted_codes("admin"))
def test_codes_have_layout_and_check_character(org: str, admin: str, bad: str) -> None:
    assert (len(org), len(admin)) == (64, 32)
    assert set(org + admin) <= set(s.CROCKFORD)
    assert org[-1] == s.check_char(org[:-1]) and admin[-1] == s.check_char(admin[:-1])
    assert bad[-1] != s.check_char(bad[:-1])


@settings(max_examples=50)
@given(s.sentences())
def test_sentences_contain_their_numbers_and_tags(sentence: s.Sentence) -> None:
    assert sentence.text.endswith(".")
    assert all(n in sentence.text for n in sentence.numbers)
    assert all(f"[chunk_{t}]" in sentence.text for t in sentence.tags)


@settings(max_examples=50)
@given(s.audit_event_sequences(), s.timed_attempt_sequences())
def test_sequences_are_time_ordered(events: list[s.AuditEvent], attempts: list[s.Attempt]) -> None:
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    assert len({e.workspace_id for e in events}) == 1
    assert [a.at for a in attempts] == sorted(a.at for a in attempts)
