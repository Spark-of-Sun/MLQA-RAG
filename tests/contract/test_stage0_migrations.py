"""KD-12 / DEV-49: the Alembic revisions are thin wrappers over the reviewed SQL in db/migrations/."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from hypothesis import given
from hypothesis import strategies as st

from lmqa_db.migrate import alembic_config, legacy_head
from lmqa_db.migrations import SQL_DIR

pytestmark = [pytest.mark.stage0, pytest.mark.contract]

# Stage 0 wraps 0001 to 0005; 0006 to 0008 become revisions in Stage 1 (task 3.1).
STAGE0_FILES = [
    "0001_schema",
    "0002_conversations",
    "0003_shares_profiles",
    "0004_retrieval",
    "0005_embedding_model",
]


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def test_revisions_are_a_linear_chain_over_the_sql_files() -> None:
    script = _script()
    base_first = [r.revision for r in reversed(list(script.walk_revisions()))]
    on_disk = sorted(p.stem for p in SQL_DIR.glob("*.sql"))
    assert script.get_heads() == [base_first[-1]]
    assert base_first == on_disk[: len(base_first)]
    assert base_first[: len(STAGE0_FILES)] == STAGE0_FILES


def test_each_revision_only_executes_its_sql_file() -> None:
    for rev in _script().walk_revisions():
        tree = ast.parse(Path(rev.path).read_text(encoding="utf-8"))
        upgrade = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
        )
        assert ast.unparse(upgrade.body) == "op.execute(sql_file(revision))", rev.revision
        assert (SQL_DIR / f"{rev.revision}.sql").is_file()


def test_legacy_head_examples() -> None:
    assert legacy_head(STAGE0_FILES, set()) is None
    assert legacy_head(STAGE0_FILES, {f"{r}.sql" for r in STAGE0_FILES}) == "0005_embedding_model"
    assert (
        legacy_head(STAGE0_FILES, {"0001_schema.sql", "0003_shares_profiles.sql"}) == "0001_schema"
    )


@given(st.sets(st.sampled_from([f"{r}.sql" for r in STAGE0_FILES])))
def test_legacy_head_is_the_longest_recorded_prefix(recorded: set[str]) -> None:
    """**Validates: Requirements 78, 85** (KD-12 adoption of databases migrated by the old runner)."""
    head = legacy_head(STAGE0_FILES, recorded)
    n = 0 if head is None else STAGE0_FILES.index(head) + 1
    assert all(f"{r}.sql" in recorded for r in STAGE0_FILES[:n])
    assert n == len(STAGE0_FILES) or f"{STAGE0_FILES[n]}.sql" not in recorded
