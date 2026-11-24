"""Execute db/migrations/0014_query_conversation_optional.sql: a question needs no chat while `chats` is off.

Revision ID: 0014_query_conversation_optional
Revises: 0013_drop_plaintext
"""

from __future__ import annotations

from alembic import op

from lmqa_db.migrations import sql_file

revision = "0014_query_conversation_optional"
down_revision: str | None = "0013_drop_plaintext"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sql_file(revision))


def downgrade() -> None:
    raise NotImplementedError("forward-only: restore from backup (blueprint 18)")
