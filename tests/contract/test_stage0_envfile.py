"""G0.6 secrets hygiene: `.env` is the only settings file, the shell overrides it, and `make setup` only fills gaps."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lmqa_models import envfile

pytestmark = [pytest.mark.contract, pytest.mark.stage0]


def _use(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(envfile, "ENV_FILE", path)
    return path


def test_env_is_the_only_file_and_the_shell_overrides_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _use(monkeypatch, tmp_path, "A_KEY=from-env\nB_KEY=from-env\nC_KEY=<placeholder>\nD_KEY=\n")
    for retired in (".secrets", ".secrets.generated"):
        (tmp_path / retired).write_text("A_KEY=retired\nE_KEY=retired\n", encoding="utf-8")
    monkeypatch.setenv("B_KEY", "from-shell")
    monkeypatch.delenv("A_KEY", raising=False)
    monkeypatch.delenv("C_KEY", raising=False)
    monkeypatch.delenv("D_KEY", raising=False)
    monkeypatch.delenv("E_KEY", raising=False)
    env = envfile.merged_env()
    assert env["A_KEY"] == "from-env"
    assert env["B_KEY"] == "from-shell"
    assert "C_KEY" not in env and "D_KEY" not in env, "placeholders and empty values count as unset"
    assert "E_KEY" not in env, ".secrets files are no longer read"
    assert not hasattr(envfile, "GENERATED") and not hasattr(envfile, "USER_FILES")


def test_fill_missing_fills_placeholders_appends_new_keys_and_never_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _use(
        monkeypatch,
        tmp_path,
        "# header\nSET_KEY=keep-me\nPH_KEY=<generated>   # note stays\nEMPTY_KEY=\n# COMMENTED_KEY=<x>\n",
    )
    path.chmod(0o644)
    written = envfile.fill_missing(
        path,
        {
            "SET_KEY": "new",
            "PH_KEY": "p1",
            "EMPTY_KEY": "e1",
            "COMMENTED_KEY": "c1",
            "NEW_KEY": "a b#c",
        },
    )
    assert sorted(written) == ["COMMENTED_KEY", "EMPTY_KEY", "NEW_KEY", "PH_KEY"]
    text = path.read_text(encoding="utf-8")
    assert "PH_KEY=p1   # note stays" in text
    assert "# COMMENTED_KEY=<x>" in text, "comments are left alone"
    assert envfile.parse_env_file(path) == {
        "SET_KEY": "keep-me",
        "PH_KEY": "p1",
        "EMPTY_KEY": "e1",
        "COMMENTED_KEY": "c1",
        "NEW_KEY": "a b#c",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert envfile.fill_missing(path, {"SET_KEY": "x", "PH_KEY": "y"}) == []
    assert not list(tmp_path.glob(".*.tmp")), "no temporary file is left behind"


def test_fill_missing_creates_env_with_mode_600(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    assert envfile.fill_missing(path, {"K": "v"}) == ["K"]
    assert envfile.parse_env_file(path) == {"K": "v"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
