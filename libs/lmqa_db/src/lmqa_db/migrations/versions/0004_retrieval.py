"""Execute db/migrations/0004_retrieval.sql (the file is the source of truth; see its header).

Revision ID: 0004_retrieval
Revises: 0003_shares_profiles
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0004_retrieval"
down_revision: str | None = "0003_shares_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
