"""Execute db/migrations/0007_identity_production.sql (the file is the source of truth; see its header).

Revision ID: 0007_identity_production
Revises: 0006_production_core
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0007_identity_production"
down_revision: str | None = "0006_production_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
