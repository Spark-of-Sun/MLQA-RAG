"""Gatekeeper verification engine for stage gate compliance.

Master System Design §19.6 & Gate Matrix.
Evaluates stage gates for specified profile (mvp-a) and stage level.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.state_machine_gen.engine import load_state_machines


@dataclass(frozen=True)
class GateResult:
    """Evaluation result for an individual gate."""

    gate_id: str
    name: str
    passed: bool
    status: str
    details: str = ""

    @classmethod
    def pass_result(cls, gate_id: str, name: str, details: str = "") -> GateResult:
        """Create a passing gate result."""
        return cls(gate_id=gate_id, name=name, passed=True, status="PASSED", details=details)

    @classmethod
    def fail_result(cls, gate_id: str, name: str, details: str = "") -> GateResult:
        """Create a failing gate result."""
        return cls(gate_id=gate_id, name=name, passed=False, status="FAILED", details=details)


class GatekeeperRunner:
    """Executes automated gate evaluations per stages.toml."""

    def __init__(self, repo_root: Path | None = None) -> None:
        """Initialize runner with repository root."""
        self.repo_root = repo_root or Path.cwd()
        self.stages_file = self.repo_root / "stages.toml"
        self.manifest_file = self.repo_root / "corpus" / "manifest.toml"

    def load_profile_config(self, profile: str) -> dict[str, Any]:
        """Load profile configuration from stages.toml."""
        if not self.stages_file.exists():
            msg = f"stages.toml not found at {self.stages_file}"
            raise FileNotFoundError(msg)
        content = self.stages_file.read_text(encoding="utf-8")
        data = tomllib.loads(content)
        profile_data = data.get("profile", {}).get(profile, {})
        return dict(profile_data)

    def check_g0_1_environment(self) -> GateResult:
        """G0.1: Reproducible environment (Python 3.14, uv.lock present)."""
        uv_lock = self.repo_root / "uv.lock"
        if not uv_lock.exists():
            return GateResult.fail_result("G0.1", "Reproducible environment", "uv.lock missing")
        return GateResult.pass_result("G0.1", "Reproducible environment", "uv.lock present")

    def check_g0_2_ruff(self) -> GateResult:
        """G0.2: Ruff format and lint clean."""
        res_fmt = subprocess.run(
            ["uv", "run", "ruff", "format", "--check", "."],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_fmt.returncode != 0:
            return GateResult.fail_result("G0.2", "Ruff format", res_fmt.stderr.strip())

        res_lint = subprocess.run(
            ["uv", "run", "ruff", "check", "."],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res_lint.returncode != 0:
            return GateResult.fail_result("G0.2", "Ruff lint", res_lint.stdout.strip())

        return GateResult.pass_result("G0.2", "Ruff", "Format and lint clean")

    def check_g0_3_types(self) -> GateResult:
        """G0.3: Pyright clean."""
        res = subprocess.run(
            ["uv", "run", "pyright"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G0.3", "Types", "pyright reported errors")
        return GateResult.pass_result("G0.3", "Types", "Pyright 0 errors")

    def check_g0_5_import_boundaries(self) -> GateResult:
        """G0.5: Import linter contracts kept."""
        res = subprocess.run(
            ["uv", "run", "lint-imports"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G0.5", "Import boundaries", "Contracts violated")
        return GateResult.pass_result("G0.5", "Import boundaries", "All contracts kept")

    def check_g0_6_secrets(self) -> GateResult:
        """G0.6: Gitleaks secrets hygiene."""
        res = subprocess.run(
            ["gitleaks", "detect", "--source", ".", "--no-banner"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G0.6", "Secrets hygiene", "Leaks detected")
        return GateResult.pass_result("G0.6", "Secrets hygiene", "No secrets detected")

    def check_g0_8_corpus(self, min_legal_docs: int = 35) -> GateResult:
        """G0.8: Corpus manifest registration and counts."""
        if not self.manifest_file.exists():
            return GateResult.fail_result("G0.8", "Corpus manifest", "manifest.toml missing")
        content = self.manifest_file.read_text(encoding="utf-8")
        docs = tomllib.loads(content).get("documents", [])
        legal_count = sum(1 for d in docs if d.get("domain") == "legal")
        if legal_count < min_legal_docs:
            msg = f"Legal documents count {legal_count} below profile minimum {min_legal_docs}"
            return GateResult.fail_result("G0.8", "Corpus manifest", msg)
        return GateResult.pass_result(
            "G0.8",
            "Corpus manifest",
            f"{len(docs)} total documents registered ({legal_count} legal)",
        )

    def check_g0_10_contracts(self) -> GateResult:
        """G0.10: State machines and authz matrix contracts validate."""
        sm_file = self.repo_root / "contracts" / "state-machines.yaml"
        authz_file = self.repo_root / "contracts" / "authz-matrix.yaml"
        if not sm_file.exists() or not authz_file.exists():
            return GateResult.fail_result("G0.10", "Contracts", "Contract YAML missing")

        try:
            registry = load_state_machines(sm_file)
            errs = registry.validate_all()
            if errs:
                return GateResult.fail_result("G0.10", "Contracts", str(errs))
        except (ValueError, KeyError, OSError) as e:
            return GateResult.fail_result("G0.10", "Contracts", f"State machines error: {e}")

        return GateResult.pass_result("G0.10", "Contracts", "Contracts validated")

    def check_g0_11_no_mocks(self) -> GateResult:
        """G0.11: No-mocks rule enforcement."""
        banned = ["unittest.mock", "pytest_mock", "respx", "responses", "faker", "factory"]
        banned_pattern = "|".join(banned)
        pattern = re.compile(
            r"^\s*(?:import\s+|from\s+)(" + banned_pattern + r")\b",
            re.MULTILINE,
        )

        for py_file in self.repo_root.glob("**/*.py"):
            if ".venv" in py_file.parts or ".git" in py_file.parts:
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            match = pattern.search(text)
            if match:
                rel = py_file.relative_to(self.repo_root)
                msg = f"Banned mock import '{match.group(1)}' found in {rel}"
                return GateResult.fail_result("G0.11", "No-mocks rule", msg)

        return GateResult.pass_result("G0.11", "No-mocks rule", "Zero mock imports found")

    def check_g1_8_audit(self) -> GateResult:
        """G1.8: Audit chain verification test."""
        res = subprocess.run(
            ["uv", "run", "pytest", "libs/lmqa_audit/tests/"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G1.8", "Audit chain", "Audit tests failed")
        return GateResult.pass_result("G1.8", "Audit chain", "Audit chain tests pass")

    def check_g1_9_state_machines(self) -> GateResult:
        """G1.9: State machine transition tests pass."""
        res = subprocess.run(
            ["uv", "run", "pytest", "tools/state_machine_gen/tests/"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G1.9", "State machines", "State machine tests failed")
        return GateResult.pass_result("G1.9", "State machines", "Transition tests pass")

    def run_stage_gates(self, stage: int, profile: str = "mvp-a") -> list[GateResult]:
        """Run all verifiable gates up to stage."""
        profile_cfg = self.load_profile_config(profile)
        min_legal = profile_cfg.get("sizes", {}).get("legal_documents_min", 35)

        results: list[GateResult] = []

        # Stage 0 Gates
        if stage >= 0:
            results.append(self.check_g0_1_environment())
            results.append(self.check_g0_2_ruff())
            results.append(self.check_g0_3_types())
            results.append(self.check_g0_5_import_boundaries())
            results.append(self.check_g0_6_secrets())
            results.append(self.check_g0_8_corpus(min_legal_docs=min_legal))
            results.append(self.check_g0_10_contracts())
            results.append(self.check_g0_11_no_mocks())

        # Stage 1 Gates
        if stage >= 1:
            results.append(self.check_g1_8_audit())
            results.append(self.check_g1_9_state_machines())

        return results
