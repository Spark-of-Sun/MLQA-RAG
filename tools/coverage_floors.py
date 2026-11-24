"""Check per-package line and branch coverage floors (blueprint 19.5, R-92).

Reads the floors from `[tool.lmqa.coverage-floors]` in `pyproject.toml` and the totals from a coverage.py JSON
report (`gates/coverage.json`, written by the gate's pytest step). Each file is assigned to the most specific
(longest) matching path prefix; files with no specific prefix are grouped by package (`libs/<name>/` or
`services/<name>/`) and held to `default`. Exits 1 when any group is below its floor.

    uv run python tools/coverage_floors.py [gates/coverage.json]
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Group:
    lines: int = 0
    covered_lines: int = 0
    branches: int = 0
    covered_branches: int = 0

    def line_percent(self) -> float:
        return 100.0 if self.lines == 0 else 100.0 * self.covered_lines / self.lines

    def branch_percent(self) -> float:
        return 100.0 if self.branches == 0 else 100.0 * self.covered_branches / self.branches


def _package_of(path: str) -> str:
    parts = path.split("/")
    return (
        "/".join(parts[:2]) + "/" if len(parts) > 2 and parts[0] in {"libs", "services"} else path
    )


def group_files(files: dict[str, dict[str, int]], prefixes: list[str]) -> dict[str, Group]:
    """Sum coverage counts per group key: the longest matching prefix, else the file's package."""
    ordered = sorted(prefixes, key=len, reverse=True)
    groups: dict[str, Group] = {}
    for path, summary in files.items():
        key = next((p for p in ordered if path.startswith(p)), None) or _package_of(path)
        group = groups.setdefault(key, Group())
        group.lines += summary.get("num_statements", 0)
        group.covered_lines += summary.get("covered_lines", 0)
        group.branches += summary.get("num_branches", 0)
        group.covered_branches += summary.get("covered_branches", 0)
    return groups


def check(files: dict[str, dict[str, int]], floors: dict[str, dict[str, float]]) -> list[str]:
    """Return one message per group below its floor; an empty list means every floor is met."""
    default = floors.get("default", {"line": 0.0, "branch": 0.0})
    specific = [k for k in floors if k != "default"]
    failures: list[str] = []
    for key, group in sorted(group_files(files, specific).items()):
        floor = floors.get(key, default)
        line, branch = group.line_percent(), group.branch_percent()
        if line < floor["line"] or branch < floor["branch"]:
            failures.append(
                f"{key}: line {line:.1f}% (floor {floor['line']}), "
                f"branch {branch:.1f}% (floor {floor['branch']})"
            )
    return failures


def main(argv: list[str]) -> int:
    report = Path(argv[1]) if len(argv) > 1 else ROOT / "gates" / "coverage.json"
    floors = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["lmqa"]["coverage-floors"]
    data = json.loads(report.read_text())
    files = {path: entry["summary"] for path, entry in data["files"].items()}
    failures = check(files, floors)
    for failure in failures:
        print(f"below floor: {failure}")
    if not failures:
        print("every coverage floor is met")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
