"""Execute db/migrations/0002_conversations.sql (the file is the source of truth; see its header).

Revision ID: 0002_conversations
Revises: 0001_schema
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0002_conversations"
down_revision: str | None = "0001_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
