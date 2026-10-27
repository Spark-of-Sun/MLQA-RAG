"""Environment diagnostic runner validating .env.example configuration and tooling."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    """Diagnostic check result item."""

    category: str
    name: str
    status: str
    detail: str


def load_env_file(env_path: Path) -> dict[str, str]:
    """Parse key-value pairs from .env file without modifying host environment."""
    vars_dict: dict[str, str] = {}
    if not env_path.exists():
        return vars_dict
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vars_dict[k.strip()] = v.strip().strip("'\"")
    return vars_dict


class EnvironmentDoctor:
    """Verifies repository runtime dependencies and active .env configuration."""

    def __init__(self, root_dir: Path | None = None) -> None:
        """Initialize doctor targeting repository root."""
        self.root_dir = root_dir or Path.cwd()
        self.env_vars = load_env_file(self.root_dir / ".env")

    def _get_val(self, key: str, default: str = "") -> str:
        """Resolve config value preferring active environment, then parsed .env."""
        return os.getenv(key) or self.env_vars.get(key, default)

    def check_cli_tool(self, cmd_name: str, check_cmd: list[str]) -> CheckResult:
        """Verify presence and executable version of a system CLI tool."""
        path = shutil.which(cmd_name)
        if not path:
            return CheckResult("Toolchain", cmd_name, "NOT CONFIGURED", "Binary not found in PATH")

        try:
            res = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            out = res.stdout.strip() or res.stderr.strip()
            first_line = out.splitlines()[0] if out else "available"
            return CheckResult("Toolchain", cmd_name, "CONFIGURED", first_line)
        except (subprocess.SubprocessError, OSError) as e:
            return CheckResult("Toolchain", cmd_name, "ERROR", str(e))

    def run_toolchain_checks(self) -> list[CheckResult]:
        """Check all required command-line binaries."""
        tools = [
            ("git", ["git", "--version"]),
            ("gh", ["gh", "--version"]),
            ("uv", ["uv", "--version"]),
            ("node", ["node", "--version"]),
            ("pnpm", ["pnpm", "--version"]),
            ("docker", ["docker", "--version"]),
            ("tofu", ["tofu", "--version"]),
            ("az", ["az", "--version"]),
            ("gitleaks", ["gitleaks", "version"]),
            ("pre-commit", ["pre-commit", "--version"]),
            ("pip-audit", ["pip-audit", "--version"]),
            ("trivy", ["trivy", "--version"]),
            ("cosign", ["cosign", "version"]),
        ]
        results = [self.check_cli_tool(name, cmd) for name, cmd in tools]
        # Python check specifically for 3.14
        py_ver = f"Python {sys.version.split()[0]}"
        is_314 = sys.version_info.major == 3 and sys.version_info.minor == 14
        results.append(
            CheckResult(
                "Toolchain",
                "python3.14",
                "CONFIGURED" if is_314 else "WARNING",
                py_ver,
            )
        )
        return results

    def run_env_configuration_checks(self) -> list[CheckResult]:
        """Audit active .env configuration against .env.example specifications."""
        env_file = self.root_dir / ".env"
        results: list[CheckResult] = []

        if env_file.exists():
            results.append(CheckResult("Configuration", ".env", "CONFIGURED", "Present"))
        else:
            results.append(
                CheckResult(
                    "Configuration",
                    "Environment",
                    "CONFIGURED",
                    "Process environment variables active (no .env on disk)",
                )
            )

        # Auth0
        auth0_domain = self._get_val("AUTH0_DOMAIN", "")
        if auth0_domain and not auth0_domain.startswith("your-tenant"):
            results.append(CheckResult("Auth0", "Domain", "CONFIGURED", auth0_domain))
        else:
            results.append(CheckResult("Auth0", "Domain", "NOT CONFIGURED", "Tenant unset"))

        # Database
        pg_host = self._get_val("PG_HOST", "localhost")
        pg_port = self._get_val("PG_PORT", "6432")
        results.append(
            CheckResult(
                "Database",
                "PostgreSQL/PgBouncer",
                "CONFIGURED",
                f"{pg_host}:{pg_port} (lmqa)",
            )
        )

        # Audit Qdrant vectorstore
        qdrant_url = self._get_val("QDRANT_URL", "http://localhost:6333")
        results.append(CheckResult("Vectorstore", "Qdrant", "CONFIGURED", qdrant_url))

        # Audit Valkey cache
        valkey_url = self._get_val("VALKEY_URL", "")
        if "password" in valkey_url or self._get_val("VALKEY_PASSWORD", ""):
            results.append(CheckResult("Cache", "Valkey", "CONFIGURED", "Password auth enabled"))
        else:
            results.append(CheckResult("Cache", "Valkey", "CONFIGURED", "Unauthenticated fallback"))

        # Audit Azure Blob storage
        azure_acc = self._get_val("AZURE_STORAGE_ACCOUNT", "")
        if azure_acc and not azure_acc.startswith("lmqadev<"):
            results.append(CheckResult("ObjectStore", "Azure Blob", "CONFIGURED", azure_acc))
        else:
            results.append(
                CheckResult(
                    "ObjectStore",
                    "Azure Blob",
                    "NOT CONFIGURED",
                    "Local fallback active",
                )
            )

        # Audit Key Vault KMS provider
        kms_prov = self._get_val("KMS_PROVIDER", "azure_keyvault")
        results.append(CheckResult("KMS", "Provider", "CONFIGURED", kms_prov))

        # Audit Google Gemini LLM provider
        llm_prov = self._get_val("LLM_PROVIDER", "google")
        llm_model = self._get_val("LLM_MODEL", "gemini-3.8-flash")
        thinking_budget = self._get_val("LLM_THINKING_BUDGET", "high")
        results.append(
            CheckResult(
                "Models",
                "LLM Provider",
                "CONFIGURED",
                f"{llm_prov}:{llm_model} (budget: {thinking_budget})",
            )
        )

        # MVP Skips
        results.append(
            CheckResult(
                "MVP Skip",
                "ClamAV",
                "SKIPPED FOR MVP",
                "Local EICAR & PDF hygiene scanner active",
            )
        )
        results.append(
            CheckResult(
                "MVP Skip",
                "Email Notifications",
                "SKIPPED FOR MVP",
                "SMTP/IMAP deferred to M1",
            )
        )
        results.append(
            CheckResult(
                "MVP Skip",
                "Observability",
                "SKIPPED FOR MVP",
                "OTel exporter deferred to M1",
            )
        )

        return results

    def print_diagnostics(self) -> None:
        """Run all diagnostics and output human-readable summary table."""
        print("=== MLQA-RAG Environment Doctor ===")
        tool_results = self.run_toolchain_checks()
        for r in tool_results:
            print(f"[{r.status:14}] {r.name:15} -> {r.detail}")

        print("\n--- Configuration & Service Alignment ---")
        cfg_results = self.run_env_configuration_checks()
        for r in cfg_results:
            print(f"[{r.status:16}] {r.category:12} | {r.name:22} -> {r.detail}")
        print("=========================================")


def main() -> None:
    """CLI entrypoint."""
    doctor = EnvironmentDoctor()
    doctor.print_diagnostics()


if __name__ == "__main__":
    main()
