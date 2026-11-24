"""Execute db/migrations/0006_production_core.sql (the file is the source of truth; see its header).

Revision ID: 0006_production_core
Revises: 0005_embedding_model
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0006_production_core"
down_revision: str | None = "0005_embedding_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
