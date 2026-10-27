"""Tests for Lifecycle State Machines and Transition Validation.

Enforces Master System Design §6 and Gate G1.9.
"""

from __future__ import annotations

import pytest

from tools.state_machine_gen.engine import load_state_machines


@pytest.fixture(scope="module")
def registry():
    return load_state_machines()


@pytest.mark.stage0
@pytest.mark.unit
def test_all_expected_lifecycles_present(registry) -> None:
    expected = {
        "document_lifecycle",
        "membership_lifecycle",
        "workspace_lifecycle",
        "organization_lifecycle",
        "join_code_lifecycle",
        "governance_request_lifecycle",
        "access_session_lifecycle",
    }
    assert expected.issubset(set(registry.machines.keys()))


@pytest.mark.stage0
@pytest.mark.unit
def test_all_lifecycle_graphs_are_valid(registry) -> None:
    validation_errors = registry.validate_all()
    assert not validation_errors, f"Graph validation errors found: {validation_errors}"


@pytest.mark.stage0
@pytest.mark.unit
def test_document_lifecycle_transitions(registry) -> None:
    doc = registry.get("document_lifecycle")
    assert doc.initial == "uploaded"

    # Legal transitions
    assert doc.can_transition("uploaded", "scanning", "scan_passed")
    assert doc.can_transition("scanning", "chunking", "parsed")
    assert doc.can_transition("chunking", "available", "indexed")
    assert doc.can_transition("available", "archived", "archive")
    assert doc.can_transition("available", "soft_deleted", "delete")
    assert doc.can_transition("soft_deleted", "purged", "purge")

    # Terminal state checks
    assert doc.is_final("purged")
    assert doc.is_final("rejected")
    assert not doc.can_transition("purged", "available")
    assert not doc.can_transition("rejected", "scanning")


@pytest.mark.stage0
@pytest.mark.unit
def test_membership_lifecycle_transitions(registry) -> None:
    mem = registry.get("membership_lifecycle")
    assert mem.initial == "pending_approval"

    # Legal transitions
    assert mem.can_transition("pending_approval", "active", "approve")
    assert mem.can_transition("active", "suspended", "suspend")
    assert mem.can_transition("suspended", "active", "reactivate")
    assert mem.can_transition("active", "removed", "remove")

    # Illegal transitions
    assert not mem.can_transition("pending_approval", "suspended")
    assert not mem.can_transition("removed", "active")


@pytest.mark.stage0
@pytest.mark.unit
def test_workspace_lifecycle_transitions(registry) -> None:
    ws = registry.get("workspace_lifecycle")
    assert ws.initial == "pending"

    assert ws.can_transition("pending", "provisioning", "approve")
    assert ws.can_transition("provisioning", "active", "provisioned")
    assert ws.can_transition("active", "frozen", "freeze")
    assert ws.can_transition("frozen", "sealed", "seal")
    assert ws.can_transition("sealed", "destroyed", "destroy")

    # Illegal
    assert not ws.can_transition("pending", "active")
    assert not ws.can_transition("destroyed", "active")


@pytest.mark.stage0
@pytest.mark.unit
def test_illegal_pairs_generation(registry) -> None:
    for name, machine in registry.machines.items():
        invalid_pairs = machine.get_invalid_pairs()
        assert len(invalid_pairs) > 0, f"[{name}] Expected illegal pairs to exist"
        # Pick first invalid pair and verify
        s1, s2 = invalid_pairs[0]
        assert not machine.can_transition(s1, s2)
