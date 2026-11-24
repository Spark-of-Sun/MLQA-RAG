"""Shared pytest rules (blueprint 19.2): every test has exactly one stage marker and exactly one kind marker.

Tests run against the real local stack (`make up`); there are no skips for a missing dependency. A test whose
dependency is down fails, so a gate result always means what it says (19.7: zero skipped checks).
"""

from __future__ import annotations

import pytest

STAGES = {f"stage{n}" for n in range(12)}
KINDS = {"unit", "integration", "contract", "e2e"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    problems: list[str] = []
    for item in items:
        names = {m.name for m in item.iter_markers()}
        stages = names & STAGES
        kinds = names & KINDS
        if len(stages) != 1 or len(kinds) != 1:
            problems.append(
                f"{item.nodeid}: stage markers {sorted(stages)}, kind markers {sorted(kinds)}"
            )
    if problems:
        raise pytest.UsageError(
            "every test needs exactly one stage marker and one of unit/integration/contract/e2e:\n  "
            + "\n  ".join(problems)
        )


@pytest.fixture(autouse=True)
def _record_markers(request: pytest.FixtureRequest) -> None:
    """Expose each test's markers in the JUnit report, so the gate attestation counts tests by marker and lane."""
    names = sorted(
        {m.name for m in request.node.iter_markers()}
        - {"parametrize", "usefixtures", "filterwarnings"}
    )
    request.node.user_properties.append(("markers", ",".join(names)))
