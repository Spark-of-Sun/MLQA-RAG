"""Every service entrypoint refuses to start, with a clear message, when its settings are missing.

Each module is imported in a clean subprocess with an empty environment. The settings are checked
before any model, database or network connection is created, so this test never loads a model.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.stage0]
ENTRYPOINTS = (
    "gateway.main",
    "identity.main",
    "ingestion.main",
    "retrieval.main",
    "generation.main",
    "citation_validator.main",
    "audit.main",
)


def _clean_env() -> dict[str, str]:
    keep = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "HOME", "LANG", "VIRTUAL_ENV", "UV_CACHE_DIR"}
    }
    return {**keep, "PYTHONWARNINGS": "ignore"}


@pytest.mark.parametrize("module", ENTRYPOINTS)
def test_an_entrypoint_without_configuration_fails_closed_with_a_clear_message(module: str) -> None:
    done = subprocess.run(  # noqa: S603 - fixed module names, no shell
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=120,
        check=False,
    )
    assert done.returncode != 0, f"{module} started without any configuration"
    assert "ConfigError" in done.stderr, done.stderr[-400:]
    assert "is not set" in done.stderr or "placeholder" in done.stderr


def test_a_placeholder_from_the_env_template_is_refused() -> None:
    code = (
        "import os; os.environ['PG_DSN_IDENTITY']='<IDENTITY_DB_PASSWORD>'; "
        "from lmqa_auth.runtime import env; env('PG_DSN_IDENTITY')"
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=_clean_env(),
        timeout=60,
        check=False,
    )
    assert done.returncode != 0
    assert "still holds the placeholder" in done.stderr
