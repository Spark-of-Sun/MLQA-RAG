"""Task 3.3: lifecycle machines as data (R-10 criteria 2, 4, 5 and 6), checked on the contract, the generated SQL and
`lmqa_models.Machine`. The database side is in tests/integration/test_stage1_lifecycle.py."""

from __future__ import annotations

import pytest
import yaml

from lmqa_models import IllegalTransition, Machine
from lmqa_models.envfile import ROOT
from lmqa_testing.tools import load_tool

DOC = yaml.safe_load((ROOT / "contracts" / "state-machines.yaml").read_text(encoding="utf-8"))
GEN = load_tool("state_machine_gen")


@pytest.mark.stage1
@pytest.mark.contract
def test_generated_revision_is_current() -> None:
    """Fails when contracts/state-machines.yaml changed without a new generated revision."""
    latest = GEN.latest()
    assert latest is not None
    assert latest.read_text(encoding="utf-8") == GEN.render(DOC), (
        f"{latest.name} is stale: python tools/state_machine_gen.py --revision NNNN_name"
    )
    assert not (
        ROOT / "db" / "policies" / "40_transitions.sql"
    ).exists()  # one home for the transitions


@pytest.mark.stage1
@pytest.mark.contract
def test_declaration_has_no_semantic_problems() -> None:
    assert GEN.problems(DOC) == []


@pytest.mark.stage1
@pytest.mark.contract
def test_nobody_changes_their_own_membership() -> None:
    """6.2, R-10.5: no membership transition lists the member; the member's columns are locked in the database."""
    membership = DOC["machines"]["membership"]
    assert all("member" not in t["actors"] for t in membership["transitions"].values())
    assert membership["actor_check"] is True
    assert {"status", "approver_id", "co_owner"} <= set(membership["subject"]["locked"])
    assert membership["subject"]["may_delete"] == ["pending_approval"]


@pytest.mark.stage1
@pytest.mark.contract
@pytest.mark.parametrize("route", ["admin_membership", "tenant_membership"])
def test_route_actions_are_approver_transitions_of_membership(route: str) -> None:
    """Every {action} route step is a `membership` pair the approver may take, so the database never refuses it."""
    membership = Machine.load("membership")
    for t in Machine.load(route).transitions.values():
        assert membership.check("approver", t.from_status, t.to_status, {"approver_active": True})


@pytest.mark.stage1
@pytest.mark.unit
def test_check_returns_the_declared_transition() -> None:
    t = Machine.load("membership").check(
        "approver", "pending_approval", "active", {"approver_active": True}
    )
    assert (t.action, t.to_status) == ("approve", "active")
    assert (
        Machine.load("membership")
        .check("system", "pending_approval", "active", {"governance_executed": True})
        .action
        == "successor_effective"
    )


@pytest.mark.stage1
@pytest.mark.unit
@pytest.mark.parametrize(
    ("actor", "frm", "to", "guards", "status", "reason"),
    [
        ("approver", "rejected", "active", {"approver_active": True}, 409, "undeclared"),
        ("approver", "active", "pending_approval", {}, 409, "undeclared"),
        ("member", "pending_approval", "active", {"approver_active": True}, 403, "actor"),
        ("other", "active", "suspended", {"approver_active": True}, 403, "actor"),
        ("approver", "pending_approval", "active", {"approver_active": False}, 403, "guard"),
        ("approver", "pending_approval", "active", None, 403, "guard"),
    ],
)
def test_check_raises_illegal_transition(  # noqa: PLR0913, PLR0917 - one parametrized case per row
    actor: str, frm: str, to: str, guards: dict[str, bool] | None, status: int, reason: str
) -> None:
    with pytest.raises(IllegalTransition) as err:
        Machine.load("membership").check(actor, frm, to, guards)
    assert (err.value.status, err.value.reason) == (status, reason)


@pytest.mark.stage1
@pytest.mark.unit
def test_workspace_approval_cannot_skip_provisioning() -> None:
    ws = Machine.load("workspace")
    with pytest.raises(IllegalTransition):
        ws.check("super_admin", "pending", "active", {"org_active": True, "provisioned": True})
    assert (
        ws.check("super_admin", "pending", "provisioning", {"org_active": True}).action == "approve"
    )
