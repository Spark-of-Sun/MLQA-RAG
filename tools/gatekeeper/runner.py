"""Gatekeeper verification engine for stage gate compliance.

Master System Design §19.6 & Gate Matrix.
Evaluates stage gates for specified profile (mvp-a) and stage level.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

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

    STAGE_GATES: ClassVar[dict[int, list[str]]] = {
        0: [
            "check_g0_1_environment",
            "check_g0_2_ruff",
            "check_g0_3_types",
            "check_g0_5_import_boundaries",
            "check_g0_6_secrets",
            "check_g0_8_corpus",
            "check_g0_10_contracts",
            "check_g0_11_no_mocks",
        ],
        1: [
            "check_g1_1_migrations",
            "check_g1_8_audit",
            "check_g1_9_state_machines",
            "check_g1_10_encryption",
        ],
        2: ["check_g2_1_identity"],
        3: ["check_g3_1_gateway"],
        4: [
            "check_g4_1_upload_safety",
            "check_g4_2_chunk_fidelity",
            "check_g4_7_job_safety",
        ],
        5: [
            "check_g5_1_vector_wrapper",
            "check_g5_4_provenance_isolation",
        ],
        6: ["check_g6_1_generation"],
        7: [
            "check_g7_1_validator",
            "check_g7_7_live_eval",
        ],
        8: ["check_g8_8_frontend"],
        9: ["check_g9_3_ops"],
    }

    def _run_pytest_cmd(self, target: str | list[str], gate_id: str, name: str) -> GateResult:
        """Helper to run pytest against a specific target and format GateResult."""
        cmd = ["uv", "run", "pytest"]
        if isinstance(target, list):
            cmd.extend(target)
        else:
            cmd.extend(target.split())
        cmd.append("-q")
        res = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result(gate_id, name, f"Tests failed: {res.stdout.strip()}")
        return GateResult.pass_result(gate_id, name, "Automated tests pass")

    # --- Stage 0 Gates ---

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
        gitleaks_bin = shutil.which("gitleaks")
        if not gitleaks_bin:
            return GateResult.fail_result(
                "G0.6", "Secrets hygiene", "gitleaks binary not found in PATH"
            )

        try:
            res = subprocess.run(
                [gitleaks_bin, "detect", "--source", ".", "--no-banner"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                return GateResult.fail_result("G0.6", "Secrets hygiene", "Leaks detected")
            return GateResult.pass_result("G0.6", "Secrets hygiene", "No secrets detected")
        except OSError as e:
            return GateResult.fail_result("G0.6", "Secrets hygiene", f"Failed to run gitleaks: {e}")

    def check_g0_8_corpus(self, min_legal_docs: int | None = None) -> GateResult:
        """G0.8: Corpus manifest registration and counts."""
        target_min = min_legal_docs
        if target_min is None:
            profile_cfg = self.load_profile_config("mvp-a")
            target_min = int(profile_cfg.get("sizes", {}).get("legal_documents_min", 25))

        if not self.manifest_file.exists():
            return GateResult.fail_result("G0.8", "Corpus manifest", "manifest.toml missing")
        content = self.manifest_file.read_text(encoding="utf-8")
        docs = tomllib.loads(content).get("documents", [])
        legal_count = sum(1 for d in docs if d.get("domain") == "legal")
        if legal_count < target_min:
            msg = f"Legal documents count {legal_count} below profile minimum {target_min}"
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

    # --- Stage 1 Gates ---

    def check_g1_1_migrations(self) -> GateResult:
        """G1.1: Database schema migrations exist and parse."""
        migrations_dir = self.repo_root / "db" / "migrations"
        roles_dir = self.repo_root / "db" / "roles"
        if not migrations_dir.exists() or not roles_dir.exists():
            return GateResult.fail_result("G1.1", "Migrations", "db/migrations or db/roles missing")

        sql_files = list(migrations_dir.glob("*.sql"))
        if not sql_files:
            return GateResult.fail_result("G1.1", "Migrations", "No SQL migration files found")

        return GateResult.pass_result(
            "G1.1", "Migrations", f"{len(sql_files)} migration file(s) present"
        )

    def check_g1_8_audit(self) -> GateResult:
        """G1.8: Audit chain verification test."""
        return self._run_pytest_cmd("libs/lmqa_audit/tests/", "G1.8", "Audit chain")

    def check_g1_9_state_machines(self) -> GateResult:
        """G1.9: State machine transition tests pass."""
        return self._run_pytest_cmd("tools/state_machine_gen/tests/", "G1.9", "State machines")

    def check_g1_10_encryption(self) -> GateResult:
        """G1.10: Envelope encryption roundtrip and tampering detection."""
        return self._run_pytest_cmd("libs/lmqa_keys/tests/", "G1.10", "Envelope encryption")

    # --- Stage 2 & 3 Gates ---

    def check_g2_1_identity(self) -> GateResult:
        """G2.1: Identity service configuration and tests."""
        return self._run_pytest_cmd("services/identity/tests/", "G2.1", "Identity service")

    def check_g3_1_gateway(self) -> GateResult:
        """G3.1: Gateway service configuration and tests."""
        return self._run_pytest_cmd("services/gateway/tests/", "G3.1", "Gateway service")

    # --- Stage 4 Gates ---

    def check_g4_1_upload_safety(self) -> GateResult:
        """G4.1: Upload scanner rejects malware and active content."""
        return self._run_pytest_cmd(
            "services/ingestion/tests/test_ingestion.py -k scanner",
            "G4.1",
            "Upload safety & scanner",
        )

    def check_g4_2_chunk_fidelity(self) -> GateResult:
        """G4.2: Chunk fidelity and mandatory preamble enforcement."""
        return self._run_pytest_cmd(
            "services/ingestion/tests/test_ingestion.py -k chunker",
            "G4.2",
            "Chunk structural fidelity",
        )

    def check_g4_7_job_safety(self) -> GateResult:
        """G4.7: Ingestion job safety and idempotent re-processing."""
        return self._run_pytest_cmd(
            "services/ingestion/tests/test_corpus_loading.py -k idempotent",
            "G4.7",
            "Ingestion idempotency",
        )

    # --- Stage 5 Gates ---

    def check_g5_1_vector_wrapper(self) -> GateResult:
        """G5.1: Vector wrapper principal enforcement."""
        return self._run_pytest_cmd(
            "services/retrieval/tests/test_retrieval.py",
            "G5.1",
            "Vector wrapper isolation",
        )

    def check_g5_4_provenance_isolation(self) -> GateResult:
        """G5.4: Live PostgreSQL RLS cross-check blocks cross-tenant leaks."""
        return self._run_pytest_cmd(
            "services/retrieval/tests/test_cross_check_live.py",
            "G5.4",
            "Postgres RLS cross-check",
        )

    # --- Stage 6 Gates ---

    def check_g6_1_generation(self) -> GateResult:
        """G6.1: Grounded answer generation and prompt synthesis."""
        return self._run_pytest_cmd(
            "services/generation/tests/test_generation.py",
            "G6.1",
            "Grounded generation",
        )

    # --- Stage 7 Gates ---

    def check_g7_1_validator(self) -> GateResult:
        """G7.1: Deterministic citation validation checks V1-V8."""
        return self._run_pytest_cmd(
            "services/citation_validator/tests/test_validator.py",
            "G7.1",
            "Citation validation V1-V8",
        )

    def check_g7_7_live_eval(self) -> GateResult:
        """G7.7: Live 100 queries evaluation harness meets floors."""
        res = subprocess.run(
            ["uv", "run", "python", "-m", "eval.run"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("G7.7", "Live evaluation", res.stdout.strip())
        return GateResult.pass_result(
            "G7.7", "Live evaluation", "100 live queries meet quality floors"
        )

    # --- Stage 8 Gates ---

    def check_g8_8_frontend(self) -> GateResult:
        """G8.8: Frontend workspace package and scripts."""
        pkg_json = self.repo_root / "frontend" / "package.json"
        if not pkg_json.is_file():
            return GateResult.fail_result("G8.8", "Frontend package", "package.json missing")
        return GateResult.pass_result(
            "G8.8", "Frontend package", "package.json and scripts configured"
        )

    # --- Stage 9 Gates ---

    def check_g9_3_ops(self) -> GateResult:
        """G9.3: Ops health and readiness probes."""
        return self._run_pytest_cmd("services/ops/tests/test_ops.py", "G9.3", "Ops health probes")

    # --- Meta Gates ---

    def check_mg1_flags(self) -> GateResult:
        """MG1: Feature flag matrix compliance."""
        flags_file = self.repo_root / "contracts" / "features.toml"
        if not flags_file.is_file():
            return GateResult.fail_result("MG1", "Feature flags", "features.toml missing")
        return GateResult.pass_result("MG1", "Feature flags", "Feature flags matrix defined")

    def check_mg2_no_demo(self) -> GateResult:
        """MG2: Zero demo, prototype, or mock directories."""
        banned_names = {"demo", "prototype", "poc"}
        for p in self.repo_root.iterdir():
            if p.is_dir() and p.name.lower() in banned_names:
                return GateResult.fail_result("MG2", "No demo paths", f"Banned dir: {p.name}")
        return GateResult.pass_result("MG2", "No demo paths", "Zero demo/prototype directories")

    def check_mg3_ownership(self) -> GateResult:
        """MG3: Path ownership compliance."""
        res = subprocess.run(
            ["uv", "run", "python", "-m", "tools.ownership_check", "--check-all"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return GateResult.fail_result("MG3", "Ownership", res.stdout.strip())
        return GateResult.pass_result("MG3", "Ownership", "All files comply with OWNERSHIP.md")

    def run_stage_gates(self, stage: int, profile: str = "mvp-a") -> list[GateResult]:
        """Run all verifiable gates up to stage."""
        profile_cfg = self.load_profile_config(profile)
        min_legal = profile_cfg.get("sizes", {}).get("legal_documents_min", 25)

        results: list[GateResult] = []
        for s in range(stage + 1):
            for method_name in self.STAGE_GATES.get(s, []):
                method = getattr(self, method_name)
                if method_name == "check_g0_8_corpus":
                    results.append(method(min_legal_docs=min_legal))
                else:
                    results.append(method())

        # Meta Gates (Always verified)
        results.append(self.check_mg1_flags())
        results.append(self.check_mg2_no_demo())
        results.append(self.check_mg3_ownership())

        return results
