"""Tests for Gatekeeper Runner.

Enforces Master System Design §19.6.
"""

from __future__ import annotations

import pytest

from tools.gatekeeper.runner import GatekeeperRunner


@pytest.fixture(scope="module")
def runner():
    return GatekeeperRunner()


@pytest.mark.stage0
@pytest.mark.unit
def test_load_profile_config(runner) -> None:
    cfg = runner.load_profile_config("mvp-a")
    assert "required_gates" in cfg
    assert "G0.1" in cfg["required_gates"]
    assert cfg.get("sizes", {}).get("legal_documents_min") == 25


@pytest.mark.stage0
@pytest.mark.unit
def test_check_g0_1_environment(runner) -> None:
    res = runner.check_g0_1_environment()
    assert res.passed
    assert res.gate_id == "G0.1"


@pytest.mark.stage0
@pytest.mark.unit
def test_check_g0_8_corpus(runner) -> None:
    res = runner.check_g0_8_corpus(min_legal_docs=25)
    assert res.passed
    assert res.gate_id == "G0.8"


@pytest.mark.stage0
@pytest.mark.unit
def test_check_g0_10_contracts(runner) -> None:
    res = runner.check_g0_10_contracts()
    assert res.passed
    assert res.gate_id == "G0.10"


@pytest.mark.stage0
@pytest.mark.unit
def test_check_g0_11_no_mocks(runner) -> None:
    res = runner.check_g0_11_no_mocks()
    assert res.passed
    assert res.gate_id == "G0.11"
