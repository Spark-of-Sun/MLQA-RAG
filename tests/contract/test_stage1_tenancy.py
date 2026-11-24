"""Task 3.2: membership and workspace machines and the no-role-update rule, checked on the contracts and the code
(R-1 criteria 7 and 8, Q-23, DEV-17). The database side is in tests/integration/test_stage1_tenancy.py."""

from __future__ import annotations

import re

import pytest
import yaml

from identity.service import wire_status
from lmqa_models.envfile import ROOT
from lmqa_testing.tools import load_tool

pytestmark = [pytest.mark.stage1, pytest.mark.contract]

MACHINES_DOC = yaml.safe_load(
    (ROOT / "contracts" / "state-machines.yaml").read_text(encoding="utf-8")
)
MACHINES = MACHINES_DOC["machines"]
STATES_6_2 = {"pending_approval", "active", "rejected", "suspended", "removed"}
LIVE = {"pending_approval", "active", "suspended"}


def _pairs(machine: str) -> set[tuple[str, str]]:
    return {(t["from"], t["to"]) for t in MACHINES[machine]["transitions"].values()}


def test_membership_machine_has_the_6_2_states_and_no_way_back_to_live() -> None:
    assert set(MACHINES["membership"]["states"]) == STATES_6_2
    # rejected and removed are final: a person comes back only through a new membership (R-1.8, Q-23)
    assert not {f for f, _ in _pairs("membership")} & (STATES_6_2 - LIVE)


@pytest.mark.parametrize("mvp", ["admin_membership", "tenant_membership"])
def test_mvp_membership_machines_are_subsets_of_membership(mvp: str) -> None:
    """The database enforces only `membership`; the routes must never ask for a pair it refuses."""
    assert set(MACHINES[mvp]["states"]) <= STATES_6_2
    assert _pairs(mvp) <= _pairs("membership")


def test_admin_workspace_moves_follow_the_workspace_machine() -> None:
    ws = _pairs("workspace")
    assert ("pending", "active") not in ws
    assert {("pending", "provisioning"), ("provisioning", "active")} <= ws
    targets = {t["workspace"] for t in MACHINES["admin_membership"]["transitions"].values()}
    assert targets <= set(MACHINES["workspace"]["states"])


def test_generated_transitions_bind_memberships_and_workspaces_to_production_machines() -> None:
    gen = load_tool("state_machine_gen")
    bindings = gen.bindings(MACHINES_DOC)
    assert bindings[("memberships", "status")] == ["membership"]
    assert bindings[("workspaces", "status")] == ["workspace"]


def test_no_route_or_statement_changes_a_membership_role() -> None:
    """R-1 criterion 8: the {action} routes take machine actions only, and no code updates memberships.role."""
    actions = {
        a for m in ("admin_membership", "tenant_membership") for a in MACHINES[m]["transitions"]
    }
    assert not {a for a in actions if "role" in a or "promote" in a or "demote" in a}
    matrix = yaml.safe_load((ROOT / "contracts" / "authz-matrix.yaml").read_text(encoding="utf-8"))
    assert not [r["path"] for r in matrix["routes"] if "role" in r["path"]]
    # `role =` inside the SET list, before any WHERE
    role_update = re.compile(
        r"update\s+memberships\s+set\b(?:(?!\bwhere\b)[^\"'])*?\brole\s*=", re.IGNORECASE
    )
    offenders = [
        str(p.relative_to(ROOT))
        for top in ("services", "libs", "tools")
        for p in (ROOT / top).rglob("*.py")
        if ".venv" not in p.parts and role_update.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_wire_status_examples() -> None:
    assert wire_status("pending_approval") == "pending"
    for status in STATES_6_2 - {"pending_approval"}:
        assert wire_status(status) == status
