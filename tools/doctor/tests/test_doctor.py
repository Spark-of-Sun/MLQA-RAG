"""Unit tests for environment doctor diagnostics without mocks."""

from __future__ import annotations

import pytest

from tools.doctor.main import EnvironmentDoctor


@pytest.mark.stage0
@pytest.mark.unit
def test_doctor_toolchain_checks() -> None:
    """Verify toolchain runner identifies present Python and uv."""
    doctor = EnvironmentDoctor()
    results = doctor.run_toolchain_checks()
    assert len(results) > 0

    names = [r.name for r in results]
    assert "uv" in names
    assert "python3.14" in names

    py_res = next(r for r in results if r.name == "python3.14")
    assert py_res.status == "CONFIGURED"


@pytest.mark.stage0
@pytest.mark.unit
def test_doctor_env_configuration_checks() -> None:
    """Verify env configuration checks categorize services accurately."""
    doctor = EnvironmentDoctor()
    results = doctor.run_env_configuration_checks()
    assert len(results) > 0

    categories = {r.category for r in results}
    assert "Database" in categories
    assert "Vectorstore" in categories
    assert "Cache" in categories
    assert "KMS" in categories
    assert "MVP Skip" in categories

    mvp_skips = [r for r in results if r.category == "MVP Skip"]
    assert len(mvp_skips) == 3
    for s in mvp_skips:
        assert s.status == "SKIPPED FOR MVP"
