"""The stage gate (doc 19.6): run every check up to a stage and write a gate attestation.

    uv run python tools/gatekeeper.py 3            # cumulative gate for stage 3
    uv run python tools/gatekeeper.py 3 --profile mvp

Order: uv sync --frozen, ruff format --check, ruff check, pyright, import-linter, gitleaks (if
installed), pytest for every stage marker from 0 to n (excluding live_models and live_aws unless the
profile asks for them), then ``gates/stage-n.json`` with the commit, tool versions, the ruff
configuration hash, test counts and the live-lane counts. A gate result is only as honest as this
file: skipped lanes are LISTED, never hidden. In CI the file is signed with cosign and published as
an attestation for that commit (the MVP does not sign locally).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MVP_SKIPS = ("live_models", "live_aws", "live_auth0", "live_llm", "perf", "chaos")


def run(label: str, command: list[str], results: dict[str, str]) -> bool:
    print(f"==> {label}")
    done = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
    results[label] = "pass" if done.returncode == 0 else "FAIL"
    return done.returncode == 0


def version(cmd: list[str]) -> str:
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603
    return (
        (done.stdout or done.stderr).strip().splitlines()[0]
        if (done.stdout or done.stderr)
        else "unknown"
    )


def main(argv: list[str]) -> int:
    stage = (
        int(argv[0]) if argv and argv[0].isdigit() else int((ROOT / "STAGE").read_text().strip())
    )
    profile = argv[argv.index("--profile") + 1] if "--profile" in argv else "mvp"
    stages = tomllib.loads((ROOT / "stages.toml").read_text(encoding="utf-8"))
    markers = " or ".join(f"stage{n}" for n in range(stage + 1))
    skipped = [m for m in MVP_SKIPS if profile == "mvp"]
    expr = f"({markers})" + "".join(f" and not {m}" for m in skipped)
    results: dict[str, str] = {}
    ok = True
    ok &= run("uv sync --frozen", ["uv", "sync", "--frozen", "--all-packages"], results)
    ok &= run("ruff format --check", ["uv", "run", "ruff", "format", "--check"], results)
    ok &= run("ruff check", ["uv", "run", "ruff", "check"], results)
    ok &= run("pyright", ["uv", "run", "pyright"], results)
    ok &= run("import-linter", ["uv", "run", "lint-imports"], results)
    if shutil.which("gitleaks"):
        ok &= run("gitleaks", ["gitleaks", "detect", "--no-banner", "--redact"], results)
    else:
        results["gitleaks"] = "SKIPPED (not installed)"
    report = ROOT / "gates" / f"pytest-stage-{stage}.xml"
    report.parent.mkdir(exist_ok=True)
    ok &= run(
        f"pytest -m '{expr}'",
        ["uv", "run", "pytest", "-q", "-m", expr, f"--junitxml={report}"],
        results,
    )
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if report.is_file():
        head = report.read_text(encoding="utf-8")[:600]
        for key in counts:
            m = re.search(rf'{key}="(\d+)"', head)
            counts[key] = int(m.group(1)) if m else 0
    owners = stages.get("stage", {}).get(str(stage), {}).get("owns", [])
    attestation = {
        "stage": stage,
        "profile": profile,
        "passed": bool(ok),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": version(["git", "rev-parse", "HEAD"]),
        "tools": {
            "python": sys.version.split()[0],
            "uv": version(["uv", "--version"]),
            "ruff": version(["uv", "run", "ruff", "--version"]),
            "pytest": version(["uv", "run", "pytest", "--version"]),
        },
        "ruff_config_sha256": hashlib.sha256(
            json.dumps(
                tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
                .get("tool", {})
                .get("ruff", {}),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "checks": results,
        "tests": counts,
        "lanes_skipped_in_this_profile": skipped,
        "stage_owns": owners,
        "signed": False,
    }
    out = ROOT / "gates" / f"stage-{stage}.json"
    out.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(
        f"\nwrote {out}: {'PASS' if ok else 'FAIL'} ({counts['tests']} tests; skipped lanes: {', '.join(skipped) or 'none'})"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
