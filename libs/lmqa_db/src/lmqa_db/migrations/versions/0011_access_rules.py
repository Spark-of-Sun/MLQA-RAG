"""Execute db/migrations/0011_access_rules.sql: rules 7a and 7b migrated out of the access decision (DEV-14).

Revision ID: 0011_access_rules
Revises: 0010_lifecycle_machines
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0011_access_rules"
down_revision: str | None = "0010_lifecycle_machines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
