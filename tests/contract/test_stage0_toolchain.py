"""Stage 0 toolchain gates: G0.1 reproducibility, G0.5 import boundaries, G0.6 secrets hygiene, G0.10 contracts,
G0.11 the no-mocks rule, G0.12 documentation. Each control (tests/controls.md) proves its check can fail.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tomllib
from pathlib import Path

import jsonschema
import pytest
import yaml
from openapi_spec_validator import validate as validate_openapi

from lmqa_models.envfile import ROOT
from lmqa_testing.tools import load_tool

pytestmark = [pytest.mark.stage0, pytest.mark.contract]

VENV_BIN = Path(sys.executable).parent


def _run(*cmd: str, cwd: Path = ROOT, stdin: str | None = None, env: dict[str, str] | None = None):
    exe = shutil.which(cmd[0]) or shutil.which(cmd[0], path=str(VENV_BIN))
    assert exe, f"{cmd[0]} is not installed"
    return subprocess.run(  # noqa: S603 - test runs resolved toolchain binaries
        [exe, *cmd[1:]], cwd=cwd, input=stdin, capture_output=True, text=True, check=False, env=env
    )


# --- G0.1 reproducible environment -----------------------------------------------------------------------------


def test_python_is_3_14() -> None:
    assert sys.version_info[:2] == (3, 14)
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.14"


def test_lockfile_matches_the_project() -> None:
    result = _run("uv", "lock", "--check")
    assert result.returncode == 0, result.stderr


def test_version_ledger_equals_the_lockfiles() -> None:
    gen = load_tool("gen_versions")
    ledger = gen.read_ledger()
    assert ledger.get("Python packages") == gen.python_packages(), (
        "uv.lock and docs/versions.md differ"
    )
    assert ledger.get("Frontend packages") == gen.frontend_packages(), (
        "pnpm-lock.yaml and docs/versions.md differ"
    )
    assert ledger.get("Container images") == gen.container_images(), (
        "compose.yaml and docs/versions.md differ"
    )


def test_tool_versions_equal_the_ledger() -> None:
    gen = load_tool("gen_versions")
    assert gen.read_ledger()["Toolchain"] == gen.toolchain()


_PINNED_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[\w][\w.-]*@sha256:[0-9a-f]{64}$")


def unpinned_images(compose: dict) -> list[str]:
    """Services in every profile whose image is not `name:tag@sha256:<64 hex>` (R-85 criterion 4, DEV-44)."""
    return [
        name
        for name, svc in compose.get("services", {}).items()
        if not _PINNED_IMAGE.fullmatch(str(svc.get("image", "")))
    ]


def test_every_image_is_pinned_by_digest() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert unpinned_images(compose) == [], (
        "images not pinned as name:tag@sha256:<digest> (4.5 adoption policy)"
    )


@pytest.mark.control
def test_control_the_pin_check_rejects_unpinned_images() -> None:
    digest = "sha256:" + "a" * 64
    compose = {
        "services": {
            "ok": {"image": f"grafana/otel-lgtm:0.41.1@{digest}"},
            "tag_only": {"image": "grafana/otel-lgtm:latest"},
            "digest_without_tag": {"image": f"grafana/otel-lgtm@{digest}"},
            "short_digest": {"image": "valkey/valkey:9@sha256:abc"},
            "build_only": {"build": "."},
        }
    }
    assert unpinned_images(compose) == [
        "tag_only",
        "digest_without_tag",
        "short_digest",
        "build_only",
    ]


# --- G0.5 import boundaries ------------------------------------------------------------------------------------


def test_import_contracts_are_kept() -> None:
    result = _run("lint-imports")
    assert result.returncode == 0, result.stdout[-2000:]
    assert "0 broken" in result.stdout


@pytest.mark.control
def test_control_violating_package_breaks_a_contract(tmp_path: Path) -> None:
    config = tmp_path / "control.importlinter"
    config.write_text(
        "[importlinter]\n"
        "root_packages =\n    lmqa_control_violation\n    lmqa_vectorstore\n\n"
        "[importlinter:contract:control]\n"
        "name = Control package must not reach vectors\n"
        "type = forbidden\n"
        "source_modules =\n    lmqa_control_violation\n"
        "forbidden_modules =\n    lmqa_vectorstore\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tests" / "controls")}
    result = _run("lint-imports", "--config", str(config), "--no-cache", env=env)
    assert result.returncode != 0, "import-linter passed a package that violates its contract"
    assert "BROKEN" in result.stdout


# --- G0.6 secrets hygiene --------------------------------------------------------------------------------------


def test_env_is_ignored_and_example_is_tracked() -> None:
    assert _run("git", "check-ignore", "-q", ".env").returncode == 0, ".env must be ignored"
    assert _run("git", "check-ignore", "-q", ".env.example").returncode == 1, (
        ".env.example must not be ignored"
    )
    assert (ROOT / ".env.example").is_file()


def test_env_example_holds_no_secret_values() -> None:
    secretish = {"KEY", "KEYS", "SECRET", "TOKEN", "PASSWORD", "CREDS", "PEPPER"}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        name, sep, rest = line.partition("=")
        is_secret = bool(set(name.split("_")) & secretish) or name.startswith("VALKEY_USER_")
        if not sep or line.startswith("#") or not is_secret:
            continue
        value = rest.split("#", 1)[0].strip()
        entries = [v for v in value.split(",") if v]
        assert all(v.startswith("<") and v.endswith(">") for v in entries), (
            f"{name} has a value, not a placeholder"
        )


def test_gitleaks_finds_nothing_in_what_git_would_commit(tmp_path: Path) -> None:
    """Tracked and committable files as they are now (ignored local secrets such as .env are out of scope)."""
    files = _run(
        "git", "ls-files", "--cached", "--others", "--exclude-standard"
    ).stdout.splitlines()
    for rel in files:
        src = ROOT / rel
        if src.is_file() and src.stat().st_size < 5_000_000:
            dst = tmp_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    shutil.copyfile(ROOT / ".gitleaksignore", tmp_path / ".gitleaksignore")
    result = _run("gitleaks", "dir", str(tmp_path), "--redact", "--no-banner", "--exit-code", "1")
    assert result.returncode == 0, "gitleaks found a secret in a file git would commit"


def test_gitleaks_history_is_clean() -> None:
    result = _run("gitleaks", "git", ".", "--redact", "--no-banner", "--exit-code", "1")
    assert result.returncode == 0, (
        "gitleaks found a secret in the git history (or .gitleaksignore is stale)"
    )


@pytest.mark.control
def test_control_planted_secret_is_detected(tmp_path: Path) -> None:
    alphabet = string.ascii_uppercase + "234567"
    planted = "AKIA" + "".join(secrets.choice(alphabet) for _ in range(16))
    (tmp_path / "settings.py").write_text(f'AWS_ACCESS_KEY_ID = "{planted}"\n', encoding="utf-8")
    result = _run("gitleaks", "dir", str(tmp_path), "--redact", "--no-banner", "--exit-code", "1")
    assert result.returncode == 1, "gitleaks missed a planted access key"
    assert planted not in result.stdout + result.stderr, "gitleaks output must be redacted"


# --- G0.10 contracts -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["authz-matrix", "state-machines"])
def test_contract_files_validate_against_their_schemas(name: str) -> None:
    schema = json.loads(
        (ROOT / "contracts" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
    )
    doc = yaml.safe_load((ROOT / "contracts" / f"{name}.yaml").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(doc, schema)


def test_state_machine_transitions_reference_declared_states() -> None:
    doc = yaml.safe_load((ROOT / "contracts" / "state-machines.yaml").read_text(encoding="utf-8"))
    for machine, spec in doc["machines"].items():
        states = set(spec["states"])
        for action, t in spec["transitions"].items():
            assert {t["from"], t["to"]} <= states, f"{machine}.{action} uses an undeclared state"


def test_openapi_is_current_and_valid() -> None:
    exporter = load_tool("export_openapi")
    committed = exporter.OUT.read_text(encoding="utf-8")
    assert committed == exporter.export(), (
        "contracts/openapi/gateway.json is stale (make contracts)"
    )
    validate_openapi(json.loads(committed))


def test_openapi_and_authz_matrix_agree() -> None:
    spec = json.loads(load_tool("export_openapi").OUT.read_text(encoding="utf-8"))
    in_spec = {
        (m.upper(), p) for p, ops in spec["paths"].items() for m in ops if p.startswith("/v1/")
    }
    matrix = yaml.safe_load((ROOT / "contracts" / "authz-matrix.yaml").read_text(encoding="utf-8"))
    in_matrix = {(r["method"], r["path"]) for r in matrix["routes"]}
    assert in_spec == in_matrix


def test_generated_typescript_client_matches_the_contract() -> None:
    generated = ROOT / "frontend" / "src" / "lib" / "api-schema.d.ts"
    assert generated.is_file(), "run make contracts"
    spec = json.loads(load_tool("export_openapi").OUT.read_text(encoding="utf-8"))
    text = generated.read_text(encoding="utf-8")
    for path in spec["paths"]:
        assert f'"{path}"' in text, f"{path} missing from the generated client (make contracts)"


def test_feature_flags_are_bound_to_gates() -> None:
    features = tomllib.loads((ROOT / "contracts" / "features.toml").read_text(encoding="utf-8"))[
        "feature"
    ]
    for name, spec in features.items():
        assert spec["gates"], f"{name} is bound to no gate"
        assert all(g.startswith("G") and "." in g for g in spec["gates"]), name
    assert (
        _run("uv", "run", "--frozen", "python", "tools/gatekeeper.py", "features").returncode == 0
    )


# --- G0.11 the no-mocks rule -----------------------------------------------------------------------------------


def test_no_fake_data_or_mocking_packages_in_the_lockfile() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = {p["name"] for p in lock["package"]}
    banned = {"faker", "factory-boy", "pytest-mock", "respx", "responses", "freezegun", "mock"}
    assert not names & banned, f"banned packages in uv.lock: {sorted(names & banned)}"


@pytest.mark.control
@pytest.mark.parametrize("module", ["unittest.mock", "faker", "freezegun", "pytest_mock"])
def test_control_banned_import_fails_ruff(module: str) -> None:
    source = f"import {module}\n"
    result = _run(
        "ruff",
        "check",
        "--no-cache",
        "--select",
        "TID251",
        "--stdin-filename",
        "services/gateway/src/x.py",
        "-",
        stdin=source,
    )
    assert result.returncode == 1, f"ruff accepted `import {module}`"
    assert "TID251" in result.stdout


# --- gatekeeper (19.6) -----------------------------------------------------------------------------------------


def test_gatekeeper_ownership_prefers_the_most_specific_pattern() -> None:
    gk = load_tool("gatekeeper")
    assert gk.owner("libs/lmqa_models/src/lmqa_models/settings.py") == 0
    assert gk.owner("libs/lmqa_models/src/lmqa_models/principal.py") == 2
    assert gk.owner("services/gateway/src/gateway/app.py") == 3
    assert gk.owner("db/policies/20_rls.sql") == 1


def test_every_tracked_file_has_an_owning_stage() -> None:
    gk = load_tool("gatekeeper")
    stages = gk.load_stages()
    tracked = _run("git", "ls-files").stdout.split()
    orphans = [p for p in tracked if gk.owner(p, stages) is None]
    assert not orphans, f"files owned by no stage: {orphans[:20]}"


def test_gatekeeper_refuses_to_advance_without_an_attestation(tmp_path: Path) -> None:
    gk = load_tool("gatekeeper")
    ok, why = gk.valid_attestation(99, "0" * 40)
    assert not ok
    assert "no attestation" in why


# --- G0.12 documentation ---------------------------------------------------------------------------------------


def test_adrs_0001_to_0012_exist() -> None:
    adr = ROOT / "docs" / "adr"
    numbers = sorted(p.name[:4] for p in adr.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert numbers[:12] == [f"{n:04d}" for n in range(1, 13)]


def test_relative_links_in_docs_resolve() -> None:
    import re

    broken = []
    for md in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", md.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (md.parent / target).resolve().exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, broken
