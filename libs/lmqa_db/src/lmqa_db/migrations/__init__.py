"""Alembic revisions for the schema in `db/migrations/` (KD-12). Each revision ID is the SQL file's stem."""

from __future__ import annotations

from lmqa_models.envfile import ROOT

SQL_DIR = ROOT / "db" / "migrations"


def sql_file(revision: str) -> str:
    """The reviewed SQL for a revision; the file is the source of truth, the revision only executes it."""
    return (SQL_DIR / f"{revision}.sql").read_text(encoding="utf-8")
