"""Execute db/migrations/0015_audit_chains.sql: per-workspace audit chains, monthly partitions (DEV-18).

Revision ID: 0015_audit_chains
Revises: 0014_query_conversation_optional
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0015_audit_chains"
down_revision: str | None = "0014_query_conversation_optional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
