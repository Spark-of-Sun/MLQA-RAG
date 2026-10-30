"""Root pytest configuration: real-system fixtures and the marker rules (doc section 19.2)."""

import re

import pytest

pytest_plugins = ["lmqa_testing.fixtures"]

_STAGE = re.compile(r"^stage(\d|1[01])$")
_KIND = {"unit", "integration", "contract", "e2e"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test carries exactly one stage marker and at least one kind marker (doc 19.2).

    A test without a stage marker would never run in any stage gate, which is a silent hole.
    """
    problems: list[str] = []
    for item in items:
        names = {m.name for m in item.iter_markers()}
        stages = {n for n in names if _STAGE.match(n)}
        if len(stages) != 1:
            problems.append(f"{item.nodeid}: needs exactly one stageN marker, has {sorted(stages)}")
        if not names & _KIND and not names & {"isolation", "perf", "chaos", "control"}:
            problems.append(f"{item.nodeid}: needs one of unit/integration/contract/e2e")
    if problems:
        raise pytest.UsageError("marker rule violations:\n  " + "\n  ".join(problems[:20]))
