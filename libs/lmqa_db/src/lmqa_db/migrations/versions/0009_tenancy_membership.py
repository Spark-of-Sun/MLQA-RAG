"""Execute db/migrations/0009_tenancy_membership.sql (the file is the source of truth; see its header).

Revision ID: 0009_tenancy_membership
Revises: 0008_streaming_release
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0009_tenancy_membership"
down_revision: str | None = "0008_streaming_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
