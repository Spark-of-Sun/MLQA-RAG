"""The gatekeeper (blueprint 19.6): stage ownership, cumulative gates, attestations, stage advance, feature flags.

  gatekeeper.py gate [--stage N] [--profile full]   run every gate step for stages 0..N, write gates/stage-N.json
  gatekeeper.py paths [--base REF]                  rule 1: changed paths must be owned by stages <= STAGE + 1
  gatekeeper.py advance                             rule 2: STAGE -> STAGE + 1 only with a passing attestation
                                                    for STAGE on the exact HEAD commit, clean tree, live lanes run
  gatekeeper.py features                            a flag is enabled only if its bound gates' stages attest pass
                                                    and it waits on no open question (`pending`)
  gatekeeper.py owner PATH...                       print the owning stage of each path

The attestation records the commit, tool versions, the ruff configuration hash, test counts by marker, coverage,
live-lane counts, step durations and the verdict. CI signs it with cosign keyless signing; a local run is unsigned
and marked so. Every gate run also appends one line to `gates/history.jsonl`, which `valid_attestation` reads to
require two clean, zero-skip, zero-waiver CI passes in a row (R-93.8) before a stage counts as done. `advance` and
`features` commit `gates/stage-N.json`, its `*.sigstore.json` bundle and `gates/history.jsonl` together so later
runs (and other clones) see the same history.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STAGES_FILE = ROOT / "stages.toml"
STAGE_FILE = ROOT / "STAGE"
GATES_DIR = ROOT / "gates"
FEATURES_FILE = ROOT / "contracts" / "features.toml"
KIND_MARKERS = ("unit", "integration", "contract", "e2e")
LANE_MARKERS = ("live_auth0", "live_kms", "live_llm", "isolation", "perf", "chaos", "control")


def load_stages() -> dict[str, Any]:
    return tomllib.loads(STAGES_FILE.read_text(encoding="utf-8"))


def current_stage() -> int:
    return int(STAGE_FILE.read_text(encoding="utf-8").strip())


def _match(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return fnmatch.fnmatchcase(path, pattern)


def owner(path: str, stages: dict[str, Any] | None = None) -> int | None:
    """The stage owning `path`: the longest matching pattern wins; None when no stage owns it."""
    stages = stages or load_stages()
    best: tuple[int, int] | None = None  # (pattern length, stage)
    for key, spec in stages["stage"].items():
        for pattern in spec.get("owns", []):
            if _match(path, pattern) and (best is None or len(pattern) > best[0]):
                best = (len(pattern), int(key))
    return best[1] if best else None


def _git(*args: str) -> str:
    git = shutil.which("git")
    if not git:
        raise SystemExit("git is required")
    return subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout  # noqa: S603 - git with internal args


def changed_paths(base: str) -> list[str]:
    committed = _git("diff", "--name-only", f"{base}...HEAD").split()
    working = _git("status", "--porcelain", "--untracked-files=all").splitlines()
    return sorted({*committed, *(line[3:].split(" -> ")[-1] for line in working if line.strip())})


def check_paths(base: str) -> int:
    stages = load_stages()
    limit = current_stage() + 1
    problems = []
    for path in changed_paths(base):
        stage = owner(path, stages)
        if stage is None:
            problems.append(f"{path}: owned by no stage (add it to stages.toml)")
        elif stage > limit:
            problems.append(
                f"{path}: stage {stage} code, but STAGE is {limit - 1} (allowed up to {limit})"
            )
    for line in problems:
        print(f"gatekeeper: {line}")
    print(f"gatekeeper: paths {'REJECTED' if problems else 'ok'} (STAGE={limit - 1})")
    return 1 if problems else 0


# --- gate run --------------------------------------------------------------------------------------------------


def ruff_config_hash() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff = json.dumps(pyproject.get("tool", {}).get("ruff", {}), sort_keys=True)
    return hashlib.sha256(ruff.encode()).hexdigest()


def _versions() -> dict[str, str]:
    ledger = ROOT / "docs" / "versions.md"
    rows = re.findall(
        r"^\| `([^`]+)` \| `([^`]*)` \|", ledger.read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    wanted = {"python", "uv", "ruff", "pyright", "node", "pnpm", "pytest"}
    return {k: v for k, v in rows if k in wanted}


def _junit_counts(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()  # noqa: S314 - parses JUnit XML this tool just wrote
    counts: dict[str, Any] = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "by_marker": {}}
    by_marker: dict[str, int] = {}
    for case in root.iter("testcase"):
        outcome = "passed"
        for child in case:
            if child.tag in {"failure", "error", "skipped"}:
                outcome = {"failure": "failed", "error": "errors", "skipped": "skipped"}[child.tag]
        counts[outcome] += 1
        for prop in case.iter("property"):
            if prop.get("name") == "markers":
                for marker in (prop.get("value") or "").split(","):
                    if marker:
                        by_marker[marker] = by_marker.get(marker, 0) + 1
    counts["by_marker"] = dict(sorted(by_marker.items()))
    return counts


def _coverage(path: Path) -> dict[str, float] | None:
    if not path.is_file():
        return None
    totals = json.loads(path.read_text(encoding="utf-8")).get("totals", {})
    return {
        "line_percent": round(float(totals.get("percent_covered", 0.0)), 2),
        "branches_covered": totals.get("covered_branches", 0),
        "branches_total": totals.get("num_branches", 0),
    }


# Steps a profile may never skip (R-93.6: a profile shrinks size and scope, never a safety threshold).
NEVER_SKIP_STEPS = {
    "gitleaks",
    "pytest",
    "coverage floors",
    "ruff check",
    "feature flags bound to attested gates",
}


def validate_profiles(config: dict[str, Any]) -> None:
    for name, spec in config.get("profile", {}).items():
        unsafe = NEVER_SKIP_STEPS & set(spec.get("skip_steps", []))
        if unsafe:
            raise SystemExit(
                f"profile {name!r} in stages.toml skips safety-critical steps: {sorted(unsafe)}"
            )


def run_gate(stage: int, profile: str) -> int:  # noqa: C901, PLR0915 - one linear flow; DEV-33 follow-up
    config = load_stages()
    if profile not in config["profile"]:
        raise SystemExit(f"unknown profile {profile}")
    validate_profiles(config)
    skip = set(config["profile"][profile].get("skip_steps", []))
    markers = " or ".join(f"stage{n}" for n in range(stage + 1))
    GATES_DIR.mkdir(exist_ok=True)
    junit = GATES_DIR / f"stage-{stage}.junit.xml"
    steps: list[dict[str, Any]] = []
    tests: dict[str, Any] | None = None
    ok = True
    env = {**os.environ, "LMQA_GATE": "1"}
    for step in config["gate"]["step"]:
        name = step["name"]
        if name in skip:
            steps.append({"name": name, "result": "skipped-by-profile"})
            continue
        cmd = [part.replace("{stages}", markers) for part in step["run"]]
        if step.get("pytest"):
            cmd += [f"--junitxml={junit}", "-o", "junit_family=xunit2"]
        exe = shutil.which(cmd[0])
        print(f"\n=== gate stage {stage}: {name}", flush=True)
        t0 = time.monotonic()
        if exe is None:
            code = 127
            print(f"{cmd[0]}: not installed")
        else:
            code = subprocess.run([exe, *cmd[1:]], cwd=ROOT, env=env, check=False).returncode  # noqa: S603 - gate commands are a fixed list in this file
        result = {"name": name, "result": "pass" if code == 0 else "fail", "exit": code}
        result["seconds"] = round(time.monotonic() - t0, 2)
        steps.append(result)
        if step.get("pytest") and junit.is_file():
            tests = _junit_counts(junit)
        ok = ok and code == 0
    required_lanes = config.get("live", {}).get(str(stage), []) if profile == "full" else []
    by_marker = (tests or {}).get("by_marker", {})
    live = {lane: by_marker.get(lane, 0) for lane in required_lanes}
    missing_live = [lane for lane, n in live.items() if n == 0]
    if tests and tests["skipped"]:
        ok = False
    if missing_live:
        ok = False
    dirty = bool(_git("status", "--porcelain").strip())
    attestation = {
        "stage": stage,
        "profile": profile,
        "commit": _git("rev-parse", "HEAD").strip(),
        "dirty_tree": dirty,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool_versions": _versions(),
        "ruff_config_sha256": ruff_config_hash(),
        "steps": steps,
        "tests": tests,
        "coverage": _coverage(GATES_DIR / "coverage.json"),
        "live_lanes": live,
        "missing_live_lanes": missing_live,
        "waivers": [],  # no waiver mechanism exists yet; always empty until one is designed (R-93.8)
        "signed": False,
        "result": "pass" if ok else "fail",
    }
    out = GATES_DIR / f"stage-{stage}.json"
    out.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    record_history(attestation)
    print(
        f"\ngatekeeper: stage {stage} ({profile}) {attestation['result'].upper()} -> {out.relative_to(ROOT)}"
    )
    for s in steps:
        print(f"  {s['result']:>18}  {s['name']}")
    if tests:
        print(
            f"  tests: {tests['passed']} passed, {tests['failed']} failed, {tests['errors']} errors, "
            f"{tests['skipped']} skipped"
        )
    if missing_live:
        print(f"  live lanes with zero tests run: {', '.join(missing_live)}")
    return 0 if ok else 1


def attestation(stage: int) -> dict[str, Any] | None:
    path = GATES_DIR / f"stage-{stage}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# --- history and the twice-in-a-row rule (R-93.8) --------------------------------------------------------------


def history_path() -> Path:
    return GATES_DIR / "history.jsonl"


def record_history(att: dict[str, Any]) -> None:
    """Append one line per gate run so `passed_twice_in_a_row` can see consecutive CI results over time, not just
    the latest `gates/stage-N.json` (which a new run overwrites). `advance` must commit this file alongside the
    attestation so later clones and runs share the same history."""
    GATES_DIR.mkdir(exist_ok=True)
    entry = {
        "stage": att["stage"],
        "profile": att["profile"],
        "commit": att["commit"],
        "result": att["result"],
        "dirty_tree": att["dirty_tree"],
        "skipped": (att.get("tests") or {}).get("skipped", 0),
        "waivers": att.get("waivers", []),
        "ci": bool(os.environ.get("GITHUB_ACTIONS")),
        "created_at": att["created_at"],
    }
    with history_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _stage_history(stage: int) -> list[dict[str, Any]]:
    path = history_path()
    if not path.is_file():
        return []
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [r for r in rows if r["stage"] == stage]


def passed_twice_in_a_row(stage: int) -> tuple[bool, str]:
    """R-93.8: a stage is done only once its gate passes on a clean CI run twice in a row, with zero skipped
    checks and zero waivers each time. Local runs (no GITHUB_ACTIONS) never count towards this."""
    runs = [r for r in _stage_history(stage) if r["ci"]]
    if len(runs) < 2:
        return (
            False,
            f"stage {stage} has {len(runs)} recorded clean CI run(s); 2 in a row are required",
        )
    for run in runs[-2:]:
        if run["result"] != "pass" or run["dirty_tree"] or run["skipped"] or run["waivers"]:
            return (
                False,
                f"stage {stage}'s last two CI runs were not both a clean, zero-skip, zero-waiver pass",
            )
    return True, "ok"


# --- signature verification (R-93.2, R-93.4) --------------------------------------------------------------------


def _cosign_identity() -> tuple[str, str]:
    """The expected signer: the `gates.yml` workflow's GitHub Actions OIDC identity. Pinning to the repository
    (when known) stops a signature from any other workflow or fork from counting."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    base = rf"https://github\.com/{re.escape(repo)}" if repo else r"https://github\.com/[^/]+/[^/]+"
    return (
        rf"^{base}/\.github/workflows/gates\.yml@.+$",
        "https://token.actions.githubusercontent.com",
    )


def verify_signature(stage: int) -> tuple[bool, str]:
    """A stage counts as CI-signed only if cosign verifies its `*.sigstore.json` bundle against this exact
    `gates/stage-N.json` blob, signed by the `gates.yml` workflow's OIDC identity. No bundle and no cosign binary
    both verify as unsigned (fail closed), so an unsigned local attestation can never satisfy this and so can
    never advance STAGE on its own."""
    blob = GATES_DIR / f"stage-{stage}.json"
    bundle = GATES_DIR / f"stage-{stage}.json.sigstore.json"
    if not bundle.is_file():
        return (
            False,
            f"no signature bundle for stage {stage} (local run, or CI signing did not run)",
        )
    cosign = shutil.which("cosign")
    if cosign is None:
        return False, "cosign is not installed here; the signature cannot be verified"
    identity, issuer = _cosign_identity()
    result = subprocess.run(  # noqa: S603 - fixed argv; verifies a local file against a pinned OIDC issuer
        [
            cosign,
            "verify-blob",
            "--bundle",
            str(bundle),
            "--certificate-identity-regexp",
            identity,
            "--certificate-oidc-issuer",
            issuer,
            str(blob),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, f"cosign rejected the stage {stage} signature: {result.stderr.strip()[:200]}"
    return True, "ok"


def valid_attestation(stage: int, commit: str) -> tuple[bool, str]:  # noqa: PLR0911 - one linear checklist
    att = attestation(stage)
    if att is None:
        return False, f"no attestation for stage {stage}"
    if att.get("result") != "pass":
        return False, f"stage {stage} attestation is a failure"
    if att.get("profile") != "full":
        return False, f"stage {stage} attestation uses profile {att.get('profile')}, not full"
    if att.get("commit") != commit or att.get("dirty_tree"):
        return False, f"stage {stage} attestation is for another commit or a dirty tree"
    if att.get("missing_live_lanes"):
        return False, f"stage {stage} attestation ran no tests in {att['missing_live_lanes']}"
    if att.get("waivers"):
        return False, f"stage {stage} attestation has waivers: {att['waivers']}"
    signed, why = verify_signature(stage)
    if not signed:
        return False, f"stage {stage} attestation is not CI-signed: {why}"
    twice, why = passed_twice_in_a_row(stage)
    if not twice:
        return False, why
    return True, "ok"


def advance() -> int:
    stage = current_stage()
    head = _git("rev-parse", "HEAD").strip()
    ok, why = valid_attestation(stage, head)
    if not ok:
        print(f"gatekeeper: cannot advance from stage {stage}: {why}")
        return 1
    STAGE_FILE.write_text(f"{stage + 1}\n", encoding="utf-8")
    print(
        f"gatekeeper: STAGE {stage} -> {stage + 1}; commit STAGE with gates/stage-{stage}.json, "
        f"gates/stage-{stage}.json.sigstore.json and gates/history.jsonl"
    )
    return 0


def feature_problems(features: dict[str, dict[str, object]]) -> list[str]:
    """Flags that may not be enabled whatever the attestations say: an enabled flag that still waits on an open
    question (`pending`, the frozen MVP-only features of DEV-21)."""
    out = []
    for name, spec in features.items():
        pending = spec.get("pending")
        if spec.get("enabled") and pending:
            items = pending if isinstance(pending, list) else [pending]
            out.append(f"{name}: enabled but frozen pending {', '.join(map(str, items))}")
    return out


def check_features(path: Path = FEATURES_FILE) -> int:
    features = tomllib.loads(path.read_text(encoding="utf-8")).get("feature", {})
    head = _git("rev-parse", "HEAD").strip()
    problems = feature_problems(features)
    for name, spec in features.items():
        if not spec.get("enabled") or spec.get("pending"):
            continue
        for stage in sorted({int(g[1:].split(".")[0]) for g in spec["gates"]}):
            ok, why = valid_attestation(stage, head)
            if not ok:
                problems.append(f"{name}: enabled but {why}")
    for line in problems:
        print(f"gatekeeper: {line}")
    enabled = sum(bool(s.get("enabled")) for s in features.values())
    print(
        f"gatekeeper: features {'REJECTED' if problems else 'ok'} ({enabled} of {len(features)} enabled)"
    )
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--stage", type=int, default=None)
    g.add_argument("--profile", default="full")
    p = sub.add_parser("paths")
    p.add_argument("--base", default="origin/beta")
    sub.add_parser("advance")
    sub.add_parser("features")
    o = sub.add_parser("owner")
    o.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.cmd == "gate":
        return run_gate(current_stage() if args.stage is None else args.stage, args.profile)
    if args.cmd == "paths":
        return check_paths(args.base)
    if args.cmd == "advance":
        return advance()
    if args.cmd == "features":
        return check_features()
    for path in args.paths:
        print(f"{path}: stage {owner(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
