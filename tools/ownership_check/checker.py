"""Ownership checker for MLQA-RAG repository.

Validates file and patch changes against ownership boundaries defined in OWNERSHIP.md.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import ClassVar, NamedTuple

NUMSTAT_COLUMN_COUNT = 3


class OwnershipRule(NamedTuple):
    """An ownership pattern rule.

    Attributes:
        pattern: Path or wildcard pattern from OWNERSHIP.md.
        is_dir: Whether the pattern represents a directory tree.
        is_wildcard: Whether the pattern contains glob wildcards.
    """

    pattern: str
    is_dir: bool
    is_wildcard: bool


class OwnershipChecker:
    """Parses and validates file ownership per OWNERSHIP.md."""

    TEAM_HANDLES: ClassVar[dict[str, str]] = {
        "maya": "Maya Okafor",
        "daniel": "Daniel Reyes",
        "priya": "Priya Nair",
        "lucas": "Lucas Weber",
        "hana": "Hana Sato",
        "coordinator": "Coordinator",
    }

    PIPELINE_PATHS: ClassVar[set[str]] = {
        ".github/",
        "PATCH_WORKFLOW.md",
        "AGENTS.md",
    }

    SHARED_ALLOWED: ClassVar[set[str]] = {
        "status/SHARED_STATUS.md",
    }

    def __init__(self, repo_root: Path | None = None) -> None:
        """Initialize the checker.

        Args:
            repo_root: Path to repository root. Defaults to current working directory.
        """
        self.repo_root = repo_root or Path.cwd()
        self.ownership_file = self.repo_root / "OWNERSHIP.md"
        self.owners: dict[str, list[OwnershipRule]] = {}
        self._load_rules()

    def _load_rules(self) -> None:
        """Load ownership rules from OWNERSHIP.md."""
        if not self.ownership_file.exists():
            return

        current_owner: str | None = None
        for line in self.ownership_file.read_text(encoding="utf-8").splitlines():
            line_strip = line.strip()
            if line_strip.startswith("## "):
                header = line_strip[3:].lower()
                matched = None
                for handle in self.TEAM_HANDLES:
                    if handle in header:
                        matched = handle
                        break
                current_owner = matched
                if current_owner and current_owner not in self.owners:
                    self.owners[current_owner] = []
            elif line_strip.startswith("- `") and current_owner:
                match = re.match(r"^-\s*`([^`]+)`", line_strip)
                if match:
                    raw_rule = match.group(1).strip()
                    is_dir = raw_rule.endswith("/")
                    is_wildcard = "*" in raw_rule
                    self.owners[current_owner].append(
                        OwnershipRule(pattern=raw_rule, is_dir=is_dir, is_wildcard=is_wildcard)
                    )

    def matches_rule(self, path_str: str, rule: OwnershipRule) -> bool:
        """Check if a path matches an ownership rule.

        Args:
            path_str: Relative file path.
            rule: OwnershipRule instance.

        Returns:
            True if path matches the rule, False otherwise.
        """
        norm_path = path_str.replace("\\", "/").lstrip("/")
        if rule.is_dir:
            dir_prefix = rule.pattern.rstrip("/") + "/"
            return norm_path.startswith(dir_prefix) or norm_path == rule.pattern.rstrip("/")
        if rule.is_wildcard:
            return fnmatch.fnmatch(norm_path, rule.pattern)
        return norm_path == rule.pattern

    def check_file_ownership(self, path_str: str, owner: str) -> bool:
        """Check if a file belongs to a given owner.

        Args:
            path_str: Relative path.
            owner: Owner handle.

        Returns:
            True if path is within owner's boundary.
        """
        norm_path = path_str.replace("\\", "/").lstrip("/")
        if norm_path == f"logs/{owner}_progress.md" or norm_path in self.SHARED_ALLOWED:
            return True

        if owner == "pipeline":
            return any(
                norm_path.startswith(p) if p.endswith("/") else norm_path == p
                for p in self.PIPELINE_PATHS
            )

        rules = self.owners.get(owner, [])
        return any(self.matches_rule(norm_path, rule) for rule in rules)

    def find_owner(self, path_str: str) -> str | None:
        """Find the owner of a given file path.

        Args:
            path_str: Relative path to check.

        Returns:
            Owner handle string if found, None otherwise.
        """
        norm_path = path_str.replace("\\", "/").lstrip("/")
        if norm_path in self.SHARED_ALLOWED:
            return "shared"
        if any(
            norm_path.startswith(p) if p.endswith("/") else norm_path == p
            for p in self.PIPELINE_PATHS
        ):
            return "pipeline"

        for owner, rules in self.owners.items():
            if any(self.matches_rule(norm_path, rule) for rule in rules):
                return owner
        return None

    def check_patch(self, patch_path: Path, expected_owner: str) -> tuple[bool, list[str]]:
        """Validate paths in a patch against expected owner boundary.

        Args:
            patch_path: Path to the .patch file.
            expected_owner: Sender handle to verify.

        Returns:
            Tuple of (success_bool, list_of_violation_strings).
        """
        if not patch_path.exists():
            return False, [f"Patch file not found: {patch_path}"]

        content = patch_path.read_text(encoding="utf-8", errors="replace")
        if "\r\n" in content:
            return False, ["Patch contains CRLF line endings; LF required."]

        cmd = ["git", "apply", "--numstat", str(patch_path)]
        res = subprocess.run(cmd, check=False, cwd=self.repo_root, capture_output=True, text=True)
        if res.returncode != 0:
            return False, [f"git apply --numstat failed: {res.stderr.strip()}"]

        changed_files: list[str] = []
        for line in res.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= NUMSTAT_COLUMN_COUNT:
                changed_files.append(parts[2])

        violations: list[str] = []
        for path in changed_files:
            if not self.check_file_ownership(path, expected_owner):
                owner = self.find_owner(path) or "unowned / coordinator"
                violations.append(
                    f"Path '{path}' outside boundary for '{expected_owner}'. Owned by: '{owner}'"
                )

        return (len(violations) == 0, violations)

    def check_all_tracked_files(self) -> tuple[bool, list[str]]:
        """Verify that every tracked file in git has an assigned owner.

        Returns:
            Tuple of (success_bool, list_of_unowned_file_paths).
        """
        cmd = ["git", "ls-files"]
        res = subprocess.run(cmd, check=False, cwd=self.repo_root, capture_output=True, text=True)
        if res.returncode != 0:
            return False, [f"git ls-files failed: {res.stderr.strip()}"]

        unowned: list[str] = []
        for line in res.stdout.splitlines():
            file_path = line.strip()
            if not file_path:
                continue
            owner = self.find_owner(file_path)
            if not owner and not (
                file_path.startswith("logs/") and file_path.endswith("_progress.md")
            ):
                unowned.append(file_path)

        return (len(unowned) == 0, unowned)
