"""Stage 0 test-taxonomy, type-check and coverage settings (blueprint 19.2 to 19.6, R-90, R-92, R-93, DEV-33)."""

from __future__ import annotations

import tomllib

import pytest

from lmqa_models.envfile import ROOT
from lmqa_testing.tools import load_tool

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
STAGES = tomllib.loads((ROOT / "stages.toml").read_text())
floors_tool = load_tool("coverage_floors")


@pytest.mark.stage0
@pytest.mark.contract
def test_pytest_settings_match_r90() -> None:
    ini = PYPROJECT["tool"]["pytest"]["ini_options"]
    assert ini["minversion"] == "9.1"
    for flag in ("--strict-markers", "--strict-config", "--import-mode=importlib"):
        assert flag in ini["addopts"]
    assert ini["xfail_strict"] is True
    assert ini["asyncio_mode"] == "strict"
    assert ini["timeout"] == 180
    assert ini["filterwarnings"] == ["error"]
    declared = {m.split(":")[0] for m in ini["markers"]}
    kinds = {"unit", "integration", "contract", "e2e", "isolation", "perf", "chaos", "control"}
    lanes = {"live_auth0", "live_kms", "live_llm"}
    assert kinds | lanes | {f"stage{n}" for n in range(12)} <= declared


@pytest.mark.stage0
@pytest.mark.contract
def test_required_test_tools_are_dev_dependencies_and_no_rerun_plugin() -> None:
    names = {
        d.split(">")[0].split("<")[0].split("=")[0] for d in PYPROJECT["dependency-groups"]["dev"]
    }
    assert {"pytest-asyncio", "schemathesis", "playwright", "mutmut", "pyright"} <= names
    assert not names & {"pytest-rerunfailures", "flaky", "pytest-flakefinder"}


@pytest.mark.stage0
@pytest.mark.contract
def test_pyright_runs_in_the_full_profile_and_is_strict_on_libs() -> None:
    steps = [s["name"] for s in STAGES["gate"]["step"]]
    assert "pyright" in steps
    assert "pyright" not in STAGES["profile"]["full"].get("skip_steps", [])
    assert "libs" in PYPROJECT["tool"]["pyright"]["strict"]


@pytest.mark.stage0
@pytest.mark.contract
def test_coverage_floors_match_r92_and_no_profile_skips_them() -> None:
    assert PYPROJECT["tool"]["coverage"]["run"]["branch"] is True
    assert PYPROJECT["tool"]["coverage"]["report"]["fail_under"] >= 90
    floors = PYPROJECT["tool"]["lmqa"]["coverage-floors"]
    assert floors["default"] == {"line": 90, "branch": 85}
    for pkg in (
        "libs/lmqa_auth/",
        "libs/lmqa_keys/",
        "libs/lmqa_security/",
        "libs/lmqa_db/",
        "services/identity/",
        "services/citation_validator/",
    ):
        assert floors[pkg] == {"line": 95, "branch": 90}
    mutation = PYPROJECT["tool"]["lmqa"]["mutation-floors"]
    assert mutation["libs/lmqa_security/"] >= 75
    assert mutation["libs/lmqa_keys/"] >= 75
    assert mutation["services/citation_validator/"] >= 80
    steps = [s["name"] for s in STAGES["gate"]["step"]]
    assert steps.index("coverage floors") > steps.index("pytest")
    for profile in STAGES["profile"].values():
        assert "coverage floors" not in profile.get("skip_steps", [])


def _summary(lines: int, covered: int, branches: int, covered_branches: int) -> dict[str, int]:
    return {
        "num_statements": lines,
        "covered_lines": covered,
        "num_branches": branches,
        "covered_branches": covered_branches,
    }


FLOORS = {
    "default": {"line": 90, "branch": 85},
    "libs/lmqa_keys/": {"line": 95, "branch": 90},
    "services/gateway/src/gateway/trust.py": {"line": 95, "branch": 90},
}


@pytest.mark.stage0
@pytest.mark.unit
def test_floors_pass_when_every_group_meets_its_floor() -> None:
    files = {
        "libs/lmqa_keys/src/lmqa_keys/envelope.py": _summary(100, 96, 10, 9),
        "libs/lmqa_models/src/lmqa_models/a.py": _summary(100, 90, 20, 17),
    }
    assert floors_tool.check(files, FLOORS) == []


@pytest.mark.stage0
@pytest.mark.unit
def test_specific_floor_applies_to_its_package_and_default_to_the_rest() -> None:
    files = {
        "libs/lmqa_keys/src/lmqa_keys/envelope.py": _summary(
            100, 92, 10, 10
        ),  # meets default, not 95
        "libs/lmqa_models/src/lmqa_models/a.py": _summary(100, 92, 20, 16),  # 80 % branch < 85
    }
    failures = floors_tool.check(files, FLOORS)
    assert len(failures) == 2
    assert failures[0].startswith("libs/lmqa_keys/: line 92.0%")
    assert failures[1].startswith("libs/lmqa_models/: line 92.0% (floor 90), branch 80.0%")


@pytest.mark.stage0
@pytest.mark.unit
def test_a_file_prefix_is_grouped_apart_from_its_package() -> None:
    files = {
        "services/gateway/src/gateway/trust.py": _summary(10, 9, 0, 0),  # 90 % < 95
        "services/gateway/src/gateway/app.py": _summary(10, 10, 0, 0),
    }
    groups = floors_tool.group_files(files, [k for k in FLOORS if k != "default"])
    assert set(groups) == {"services/gateway/src/gateway/trust.py", "services/gateway/"}
    assert floors_tool.check(files, FLOORS) == [
        "services/gateway/src/gateway/trust.py: line 90.0% (floor 95), branch 100.0% (floor 90)"
    ]
