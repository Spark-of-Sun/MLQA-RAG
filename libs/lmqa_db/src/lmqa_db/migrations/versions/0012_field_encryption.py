"""Execute db/migrations/0012_field_encryption.sql: ciphertext columns, platform, cache and workspace-month audit keys.

Revision ID: 0012_field_encryption
Revises: 0011_access_rules
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0012_field_encryption"
down_revision: str | None = "0011_access_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
