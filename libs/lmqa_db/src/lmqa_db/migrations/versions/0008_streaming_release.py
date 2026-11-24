"""Execute db/migrations/0008_streaming_release.sql (the file is the source of truth; see its header).

Revision ID: 0008_streaming_release
Revises: 0007_identity_production
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0008_streaming_release"
down_revision: str | None = "0007_identity_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
