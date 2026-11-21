"""Tests generated from contracts/state-machines.yaml (G1.9, G2.9)."""

import pytest

from lmqa_models import IllegalTransitionError, StateMachine, load_machines, sql_for

pytestmark = [pytest.mark.unit, pytest.mark.stage1]

MACHINES = load_machines()
EXPECTED = {
    "membership",
    "workspace",
    "organization",
    "document",
    "join_code",
    "governance_request",
    "access_session",
}


def test_all_doc_lifecycles_are_declared() -> None:
    assert set(MACHINES) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_legal_transition_succeeds_for_each_declared_actor(name: str) -> None:
    machine = MACHINES[name]
    for t in machine.transitions:
        for actor in t.actors:
            machine.assert_transition(t.from_state, t.to_state, actor)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_legal_transition_fails_for_an_unauthorized_actor(name: str) -> None:
    machine = MACHINES[name]
    for t in machine.transitions:
        if "nobody" in t.actors:
            continue
        with pytest.raises(IllegalTransitionError):
            machine.assert_transition(t.from_state, t.to_state, "nobody")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_illegal_pair_fails_for_every_actor(name: str) -> None:
    machine = MACHINES[name]
    actors = {a for t in machine.transitions for a in t.actors}
    assert machine.illegal_pairs(), "a machine with no illegal pair is suspicious"
    for a, b in machine.illegal_pairs():
        for actor in actors:
            assert not machine.can_transition(a, b, actor)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_terminal_states_have_no_exits(name: str) -> None:
    machine = MACHINES[name]
    for t in machine.transitions:
        assert t.from_state not in machine.terminal


def test_membership_matches_doc_62() -> None:
    m = MACHINES["membership"]
    assert m.initial == "pending_approval"
    assert m.can_transition("pending_approval", "active", "approver")
    assert not m.can_transition("pending_approval", "suspended", "approver")
    assert not m.can_transition("rejected", "active", "approver")
    assert not m.can_transition("removed", "active", "approver")


def test_a_wrong_declaration_is_rejected_at_load() -> None:
    bad = {
        "name": "bad",
        "table": "t",
        "column": "c",
        "initial": "a",
        "terminal": ["b"],
        "states": ["a", "b"],
        "transitions": [{"from": "b", "to": "a", "event": "x", "actors": ["system"]}],
    }
    with pytest.raises(ValueError, match="terminal"):
        StateMachine.model_validate(bad)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_generated_sql_is_self_contained(name: str) -> None:
    sql = sql_for(MACHINES[name])
    assert f"sm_{name}_transitions" in sql
    assert "CREATE TRIGGER" in sql
    assert "23514" in sql
    assert "SECURITY DEFINER" in sql


def test_sql_generator_rejects_unsafe_identifiers() -> None:
    machine = MACHINES["membership"].model_copy(update={"table": "memberships; DROP TABLE x"})
    with pytest.raises(ValueError, match="unsafe SQL identifier"):
        sql_for(machine)
