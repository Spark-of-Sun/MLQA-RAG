"""Tests for ownership checker."""

from __future__ import annotations

import pytest

from tools.ownership_check.checker import OwnershipChecker


@pytest.mark.stage0
@pytest.mark.unit
def test_ownership_checker_rules_loaded() -> None:
    checker = OwnershipChecker()
    assert "daniel" in checker.owners
    assert "ganpati" in checker.owners
    assert "coordinator" in checker.owners


@pytest.mark.stage0
@pytest.mark.unit
def test_find_owner_core_paths() -> None:
    checker = OwnershipChecker()
    assert checker.find_owner("stages.toml") == "ganpati"
    assert checker.find_owner("db/migrations/env.py") == "ganpati"
    assert checker.find_owner("services/gateway/main.py") == "daniel"
    assert checker.find_owner("corpus/manifest.toml") == "ganpati"
    assert checker.find_owner("eval/floors.toml") == "ganpati"
    assert checker.find_owner("frontend/package.json") == "ganpati"
    assert checker.find_owner("OWNERSHIP.md") == "coordinator"
    assert checker.find_owner("status/SHARED_STATUS.md") == "shared"
    assert checker.find_owner(".github/workflows/ci.yml") == "ganpati"


@pytest.mark.stage0
@pytest.mark.unit
def test_check_file_ownership() -> None:
    checker = OwnershipChecker()
    assert checker.check_file_ownership("stages.toml", "ganpati")
    assert not checker.check_file_ownership("services/gateway/main.py", "ganpati")
    assert checker.check_file_ownership("services/gateway/main.py", "daniel")
    assert checker.check_file_ownership("logs/daniel_progress.md", "daniel")
    assert checker.check_file_ownership("status/SHARED_STATUS.md", "daniel")
    assert checker.check_file_ownership("status/SHARED_STATUS.md", "ganpati")
