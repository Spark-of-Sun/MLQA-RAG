"""Execute db/migrations/0003_shares_profiles.sql (the file is the source of truth; see its header).

Revision ID: 0003_shares_profiles
Revises: 0002_conversations
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0003_shares_profiles"
down_revision: str | None = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
