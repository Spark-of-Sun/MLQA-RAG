"""KeyGuard policy lint (doc 12.5, gate G1.12): no production key may be deleted too fast.

Scans OpenTofu files for every ``aws_kms_key``: the waiting window must be exactly 30 days unless
the key carries the ``drill`` tag (the annual full-destruction drill may use the provider's 7 day
minimum), and its key policy must be explicit, so it carries the KeyGuard deny. It also checks that
no service IAM policy grants a destructive KMS action.

    uv run python infra/keyguard/lint.py infra/aws
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PRODUCTION_WINDOW_DAYS = 30
DESTRUCTIVE = (
    "kms:ScheduleKeyDeletion",
    "kms:DisableKey",
    "kms:DeleteImportedKeyMaterial",
)
# PutKeyPolicy is allowed to exactly one service role, only to set the policy when a key is created;
# every key's own policy then denies it to everyone but the two KeyGuard roles.
_KEY = re.compile(r'resource\s+"aws_kms_key"\s+"(?P<name>\w+)"\s*\{(?P<body>.*?)\n\}', re.DOTALL)
_DOC = re.compile(
    r'data\s+"aws_iam_policy_document"\s+"(?P<name>\w+)"\s*\{(?P<body>.*?)\n\}', re.DOTALL
)
_WINDOW = re.compile(r"deletion_window_in_days\s*=\s*(?P<days>\d+)")
_POLICY = re.compile(r"\bpolicy\s*=")
_DRILL = re.compile(r'drill\s*=\s*"?true"?')


def lint_text(text: str, filename: str = "<memory>") -> list[str]:
    """Return one message per key-window or key-policy violation in one OpenTofu file."""
    problems: list[str] = []
    for match in _KEY.finditer(text):
        name, body = match["name"], match["body"]
        window = _WINDOW.search(body)
        days = int(window["days"]) if window else PRODUCTION_WINDOW_DAYS  # AWS' own default is 30
        if days != PRODUCTION_WINDOW_DAYS and not _DRILL.search(body):
            problems.append(
                f"{filename}: aws_kms_key.{name} has a {days} day deletion window "
                f"(production requires {PRODUCTION_WINDOW_DAYS})"
            )
        if not _POLICY.search(body):
            problems.append(
                f"{filename}: aws_kms_key.{name} has no explicit key policy (no KeyGuard deny)"
            )
    return problems


def lint_grants(text: str, filename: str = "<memory>") -> list[str]:
    """No policy document may grant a destructive KMS action (the deny names them on purpose)."""
    problems: list[str] = []
    for block in _DOC.finditer(text):
        if "KeyGuardDenyDestructiveActions" in block["body"]:
            continue
        problems.extend(
            f"{filename}: policy document {block['name']} grants {action}"
            for action in DESTRUCTIVE
            if action in block["body"]
        )
    return problems


def main(argv: list[str]) -> int:
    """Lint every ``*.tf`` file under a directory (default ``infra/aws``)."""
    root = Path(argv[0]) if argv else Path("infra/aws")
    problems: list[str] = []
    for path in sorted(root.rglob("*.tf")):
        text = path.read_text(encoding="utf-8")
        problems += lint_text(text, str(path)) + lint_grants(text, str(path))
    for problem in problems:
        print(problem)
    print(f"keyguard lint: {'FAIL' if problems else 'ok'} ({len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
