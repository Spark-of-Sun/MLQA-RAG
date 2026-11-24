"""Execute db/migrations/0001_schema.sql (the file is the source of truth; see its header).

Revision ID: 0001_schema
Revises: (base)
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0001_schema"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
