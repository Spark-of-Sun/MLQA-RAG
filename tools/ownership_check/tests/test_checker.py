"""Tests for ownership checker."""

from __future__ import annotations

import pytest

from tools.ownership_check.checker import OwnershipChecker


@pytest.mark.stage0
@pytest.mark.unit
def test_ownership_checker_rules_loaded() -> None:
    checker = OwnershipChecker()
    assert "maya" in checker.owners
    assert "daniel" in checker.owners
    assert "priya" in checker.owners
    assert "lucas" in checker.owners
    assert "hana" in checker.owners


@pytest.mark.stage0
@pytest.mark.unit
def test_find_owner_core_paths() -> None:
    checker = OwnershipChecker()
    assert checker.find_owner("stages.toml") == "maya"
    assert checker.find_owner("db/migrations/env.py") == "maya"
    assert checker.find_owner("services/gateway/main.py") == "daniel"
    assert checker.find_owner("corpus/manifest.toml") == "priya"
    assert checker.find_owner("eval/floors.toml") == "lucas"
    assert checker.find_owner("frontend/package.json") == "hana"
    assert checker.find_owner("OWNERSHIP.md") == "coordinator"
    assert checker.find_owner("status/SHARED_STATUS.md") == "shared"
    assert checker.find_owner(".github/workflows/ci.yml") == "pipeline"


@pytest.mark.stage0
@pytest.mark.unit
def test_check_file_ownership() -> None:
    checker = OwnershipChecker()
    assert checker.check_file_ownership("stages.toml", "maya")
    assert not checker.check_file_ownership("services/gateway/main.py", "maya")
    assert checker.check_file_ownership("services/gateway/main.py", "daniel")
    assert checker.check_file_ownership("logs/maya_progress.md", "maya")
    assert checker.check_file_ownership("status/SHARED_STATUS.md", "maya")
