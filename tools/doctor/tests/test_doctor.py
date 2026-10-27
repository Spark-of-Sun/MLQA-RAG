"""Unit tests for environment doctor diagnostics without mocks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tools.doctor.main import EnvironmentDoctor

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.stage0
@pytest.mark.unit
def test_doctor_env_configuration_checks_without_env_file(tmp_path: Path) -> None:
    """Verify env doctor passes and categorizes without a physical .env file."""
    doctor = EnvironmentDoctor(root_dir=tmp_path)
    results = doctor.run_env_configuration_checks()
    assert len(results) > 0

    categories = {r.category for r in results}
    assert "Configuration" in categories
    assert "Database" in categories
    assert "Vectorstore" in categories

    config_res = next(r for r in results if r.category == "Configuration")
    assert config_res.status == "CONFIGURED"
    assert config_res.name == "Environment"
