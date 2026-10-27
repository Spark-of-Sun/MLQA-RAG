"""CLI entry point for ownership checker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.ownership_check.checker import OwnershipChecker


def _handle_patch(checker: OwnershipChecker, patch: Path, owner: str | None) -> int:
    if not owner:
        print("Error: --owner is required when --patch is specified", file=sys.stderr)
        return 2
    ok, violations = checker.check_patch(patch, owner)
    if not ok:
        print("Ownership check FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(f"Ownership check PASSED for patch {patch.name} (owner: {owner})")
    return 0


def _handle_check_all(checker: OwnershipChecker) -> int:
    ok, unowned = checker.check_all_tracked_files()
    if not ok:
        print("Unowned files detected in repository:", file=sys.stderr)
        for f in unowned:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("All tracked files matched valid ownership rules.")
    return 0


def _handle_file(checker: OwnershipChecker, file_path: str) -> int:
    owner = checker.find_owner(file_path)
    if owner:
        print(f"'{file_path}' is owned by: {owner}")
        return 0
    print(f"'{file_path}' has NO registered owner.", file=sys.stderr)
    return 1


def main() -> int:
    """Run ownership check commands.

    Returns:
        Exit code: 0 on success, non-zero on error.
    """
    parser = argparse.ArgumentParser(description="Validate path ownership per OWNERSHIP.md")
    parser.add_argument("--patch", type=Path, help="Patch file to inspect")
    parser.add_argument("--owner", type=str, help="Expected owner handle (e.g. daniel, ganpati)")
    parser.add_argument(
        "--check-all", action="store_true", help="Verify all git tracked files have owners"
    )
    parser.add_argument("--file", type=str, help="Find owner of a specific path")
    args = parser.parse_args()

    checker = OwnershipChecker()

    if args.patch:
        return _handle_patch(checker, args.patch, args.owner)
    if args.check_all:
        return _handle_check_all(checker)
    if args.file:
        return _handle_file(checker, args.file)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
