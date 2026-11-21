"""Baseline: schema, context helpers, generated state machines, RLS, grants, triggers, audit.

Revision ID: 0001
Revises:
"""

from pathlib import Path

from alembic import op

from lmqa_models import load_machines, sql_for

revision = "0001"
down_revision = None

DB = Path(__file__).resolve().parents[2]
ORDERED = (
    "migrations/sql/010_schema_control.sql",
    "migrations/sql/020_schema_content.sql",
    "policies/030_context.sql",
    "@state_machines",
    # ALTER FUNCTION ... OWNER TO needs the new owner to hold CREATE on the schema. The grant is
    # temporary: it is revoked again after the last file (see @revoke_create).
    "@grant_create",
    "policies/040_policies.sql",
    "policies/050_grants.sql",
    "policies/060_triggers.sql",
    "policies/070_audit.sql",
    "@revoke_create",
)
HELPERS = "policy_helper, scope_maintainer, audit_definer, principal_owner"


def _run(sql: str, label: str = "") -> None:
    # Raw DBAPI cursor with no parameters: psycopg then uses the simple query protocol, which
    # allows multiple statements and leaves '%' (format('%I')) alone.
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    except Exception as exc:
        msg = f"migration step failed: {label or sql[:60]!r}: {exc}"
        raise RuntimeError(msg) from exc
    finally:
        cursor.close()


def upgrade() -> None:
    for item in ORDERED:
        if item == "@state_machines":
            for machine in load_machines().values():
                _run(sql_for(machine), f"state machine {machine.name}")
        elif item == "@grant_create":
            _run(f"GRANT CREATE ON SCHEMA public TO {HELPERS}")
        elif item == "@revoke_create":
            _run(f"REVOKE CREATE ON SCHEMA public FROM {HELPERS}")
        else:
            _run((DB / item).read_text(encoding="utf-8"), item)


def downgrade() -> None:
    _run(
        "DROP SCHEMA public CASCADE;"
        " CREATE SCHEMA public AUTHORIZATION lmqa_owner;"
        " REVOKE ALL ON SCHEMA public FROM PUBLIC;"
    )
