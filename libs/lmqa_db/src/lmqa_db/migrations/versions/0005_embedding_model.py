"""Execute db/migrations/0005_embedding_model.sql (the file is the source of truth; see its header).

Revision ID: 0005_embedding_model
Revises: 0004_retrieval
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0005_embedding_model"
down_revision: str | None = "0004_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
