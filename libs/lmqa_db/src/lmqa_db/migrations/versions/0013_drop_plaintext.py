"""Execute db/migrations/0013_drop_plaintext.sql: drop the plaintext content and contact columns (DEV-09).

Revision ID: 0013_drop_plaintext
Revises: 0012_field_encryption
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0013_drop_plaintext"
down_revision: str | None = "0012_field_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
