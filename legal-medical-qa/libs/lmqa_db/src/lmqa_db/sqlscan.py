"""Scan the repository for session-state SQL that transaction pooling breaks (doc 10.3, G1.7).

Request-path services connect through PgBouncer in transaction mode, so these statements are
banned there: session ``SET``, session advisory locks, ``LISTEN``/``NOTIFY``,
``DECLARE ... CURSOR``, ``PREPARE``/``DEALLOCATE`` and temporary tables that outlive the
transaction. Transaction-local forms (``SET LOCAL``, ``set_config(..., true)``,
``pg_advisory_xact_lock``) are fine.

Only uppercase SQL keywords are matched, which is how SQL is written in this codebase, so prose
such as "set the cache" is never flagged.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

RULES: Final = (
    # Only a SET that *starts* a statement is session state; the SET in "UPDATE t SET c = 1" is not.
    (
        "session SET",
        re.compile(
            r"(?:\A|;)\s*SET\s+(?!LOCAL\b|CONSTRAINTS\b|TRANSACTION\b|search_path\b)"
            r"(?:SESSION\s+)?[A-Za-z_.]+\s*(?:=|TO\b)"
        ),
    ),
    ("session advisory lock", re.compile(r"\bpg_(?:try_)?advisory_(?:lock|unlock)(?:_all)?\s*\(")),
    ("LISTEN/NOTIFY", re.compile(r"\b(?:LISTEN|UNLISTEN|NOTIFY)\s+\w")),
    ("cursor", re.compile(r"\bDECLARE\b[^;]*\bCURSOR\b|\bWITH\s+HOLD\b")),
    ("prepared statement", re.compile(r"\b(?:PREPARE|DEALLOCATE)\s+\w")),
    (
        "temporary table",
        re.compile(r"\bCREATE\s+TEMP(?:ORARY)?\s+TABLE\b(?![^;]*ON\s+COMMIT\s+DROP)"),
    ),
)
# Workers hold direct connections (no pooler) and may use LISTEN/NOTIFY and session locks.
DIRECT_CONNECTION_PATHS: Final = ("services/ingestion/src/ingestion/workers/",)
SKIP_PARTS: Final = (
    "/tests/",
    "/migrations/",
    "/policies/",
    "lmqa_db/sqlscan.py",
    "lmqa_db/bootstrap.py",
    "libs/lmqa_testing/",
)


@dataclass(frozen=True, slots=True)
class Violation:
    """One banned statement in one file."""

    path: str
    line: int
    rule: str
    snippet: str


def _strings(path: Path) -> list[tuple[int, str]]:
    if path.suffix == ".sql":
        return [(1, path.read_text(encoding="utf-8"))]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def scan_text(path: str, line: int, text: str) -> list[Violation]:
    """Return every banned statement found in one string."""
    return [
        Violation(path, line, name, match.group(0).strip()[:60])
        for name, pattern in RULES
        for match in pattern.finditer(text)
    ]


def scan_file(path: Path, root: Path) -> list[Violation]:
    """Scan one Python or SQL file."""
    rel = str(path.relative_to(root)) if path.is_absolute() and root in path.parents else str(path)
    if any(rel.startswith(p) for p in DIRECT_CONNECTION_PATHS):
        return []
    return [v for line, text in _strings(path) for v in scan_text(rel, line, text)]


def scan_repository(root: Path) -> list[Violation]:
    """Scan every request-path source file under ``services/*/src`` and ``libs/*/src``."""
    found: list[Violation] = []
    for pattern in ("services/*/src/**/*.py", "libs/*/src/**/*.py"):
        for path in sorted(root.glob(pattern)):
            posix = "/" + path.relative_to(root).as_posix()
            if any(part in posix for part in SKIP_PARTS):
                continue
            found.extend(scan_file(path, root))
    return found
