"""G1.6: a row cannot point into another workspace or organization (doc 5.1).

The inserts run as a superuser (BYPASSRLS) on purpose: that way the *foreign key* is the only
thing that can reject them, so the test proves the constraint and not a policy.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest

from lmqa_db import ContextRole
from lmqa_db.bootstrap import with_database
from lmqa_testing import world
from lmqa_testing.pg import superuser_dsn

if TYPE_CHECKING:
    from lmqa_testing.fixtures import Stack

pytestmark = [pytest.mark.integration, pytest.mark.stage1]


@pytest.mark.asyncio
async def test_every_composite_foreign_key_refuses_a_cross_scope_reference(
    migrated_db: str, stack: Stack
) -> None:
    org1 = await world.create_org(stack)
    org2 = await world.create_org(stack)
    a = await world.create_workspace(stack, org1)  # workspace A, org 1
    b = await world.create_workspace(stack, org1)  # workspace B, same org
    w2 = await world.create_workspace(stack, org2)  # a workspace of another org
    matter_b = await world.create_matter(stack, b)
    doc_b = await world.add_document(stack, b, b.admin, ContextRole.ADMIN, visibility="private")
    doc_a = await world.add_document(stack, a, a.admin, ContextRole.ADMIN, visibility="private")
    tenant_a = await world.create_tenant(stack, a)
    blob, digest = os.urandom(16), os.urandom(32).hex()

    # (table, SQL, params): each tries to attach a row of workspace A (or org 1) to B's/org 2's data.
    cases: dict[str, tuple[str, tuple[object, ...]]] = {
        "documents.matter": (
            "INSERT INTO documents (org_id, workspace_id, owner_user_id, matter_id, title_ciphertext,"
            " visibility, confidentiality_tier) VALUES (%s, %s, %s, %s, %s, 'matter', 1)",
            (org1.id, a.id, a.admin, matter_b, blob),
        ),
        "chunks.document": (
            "INSERT INTO chunks (org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id,"
            " visibility, confidentiality_tier, kind, page_start, page_end, text_ciphertext, text_sha256,"
            " token_count) VALUES (%s, %s, %s, 1, 99, %s, 'private', 1, 'paragraph', 1, 1, %s, %s, 5)",
            (org1.id, a.id, doc_b, a.admin, blob, digest),
        ),
        "chunks.matter": (
            "INSERT INTO chunks (org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id,"
            " matter_id, visibility, confidentiality_tier, kind, page_start, page_end, text_ciphertext,"
            " text_sha256, token_count) VALUES (%s, %s, %s, 1, 7, %s, %s, 'matter', 1, 'paragraph', 1, 1, %s, %s, 5)",
            (org1.id, a.id, doc_a, a.admin, matter_b, blob, digest),
        ),
        "document_versions.document": (
            "INSERT INTO document_versions (doc_id, org_id, workspace_id, version) VALUES (%s, %s, %s, 9)",
            (doc_b, org1.id, a.id),
        ),
        "doc_keys.document": (
            "INSERT INTO doc_keys (doc_id, org_id, workspace_id, key_version) VALUES (%s, %s, %s, 1)",
            (doc_b, org1.id, a.id),
        ),
        "matter_grants.matter": (
            "INSERT INTO matter_grants (org_id, workspace_id, matter_id, user_id, max_tier)"
            " VALUES (%s, %s, %s, %s, 1)",
            (org1.id, a.id, matter_b, tenant_a),
        ),
        "matter_walls.matter": (
            "INSERT INTO matter_walls (org_id, workspace_id, matter_id, user_id, reason_code)"
            " VALUES (%s, %s, %s, %s, 'x')",
            (org1.id, a.id, matter_b, tenant_a),
        ),
        "matters.workspace": (
            "INSERT INTO matters (org_id, workspace_id, label) VALUES (%s, %s, 'x')",
            (org1.id, w2.id),
        ),
        "memberships.workspace": (
            "INSERT INTO memberships (user_id, org_id, workspace_id, role) VALUES (%s, %s, %s, 'tenant')",
            (await world.create_user(stack), org1.id, w2.id),
        ),
        "join_codes.workspace": (
            "INSERT INTO join_codes (kind, org_id, workspace_id, lookup_id, code_hash, pepper_id,"
            " expires_at, max_uses) VALUES ('admin', %s, %s, %s, %s, 'v1', now() + interval '1 day', 5)",
            (org1.id, w2.id, uuid4().hex[:8], blob),
        ),
        "access_sessions.workspace": (
            "INSERT INTO access_sessions (org_id, workspace_id, user_id, kind, reason_code, expires_at)"
            " VALUES (%s, %s, %s, 'break_glass', 'x', now() + interval '1 hour')",
            (org1.id, w2.id, a.admin),
        ),
        "governance_requests.workspace": (
            "INSERT INTO governance_requests (org_id, workspace_id, kind, initiator_id, expires_at)"
            " VALUES (%s, %s, 'wall_lift', %s, now() + interval '1 day')",
            (org1.id, w2.id, a.admin),
        ),
        "workspace_usage.workspace": (
            "INSERT INTO workspace_usage (workspace_id, org_id) VALUES (%s, %s)",
            (w2.id, org1.id),
        ),
        "workspace_keys.workspace": (
            "INSERT INTO workspace_keys (org_id, workspace_id, version) VALUES (%s, %s, 1)",
            (org1.id, w2.id),
        ),
        "audit_keys.workspace": (
            "INSERT INTO audit_keys (org_id, workspace_id, month, public_key) VALUES (%s, %s, '2026-10-01', %s)",
            (org1.id, w2.id, blob),
        ),
        "retrieval_records.workspace": (
            "INSERT INTO retrieval_records (org_id, workspace_id, request_id, user_id, scope_hash, items)"
            " VALUES (%s, %s, %s, %s, 'h', '[]')",
            (org1.id, w2.id, uuid4(), a.admin),
        ),
        "index_outbox.workspace": (
            "INSERT INTO index_outbox (org_id, workspace_id, doc_id, doc_version, operation)"
            " VALUES (%s, %s, %s, 1, 'upsert')",
            (org1.id, w2.id, doc_b),
        ),
    }

    with psycopg.connect(with_database(superuser_dsn(), migrated_db), autocommit=True) as conn:
        # Sanity: the superuser really bypasses RLS, so a rejection can only come from a constraint.
        rolbypass = conn.execute(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert rolbypass is not None
        assert rolbypass[0]
        for name, (statement, params) in cases.items():
            try:
                with conn.transaction():
                    conn.execute(statement, params)  # type: ignore[arg-type]
            except psycopg.errors.ForeignKeyViolation:
                continue
            except psycopg.Error as exc:
                pytest.fail(
                    f"{name}: expected a foreign key violation, got {type(exc).__name__}: {exc}"
                )
            pytest.fail(f"{name}: the cross-scope reference was ACCEPTED")

        # Every composite FK in the catalog must be covered by the cases above.
        composite = {
            row[0]
            for row in conn.execute(
                "SELECT conrelid::regclass::text FROM pg_constraint"
                " WHERE contype = 'f' AND array_length(conkey, 1) > 1"
            ).fetchall()
        }
        covered = {name.split(".")[0] for name in cases}
        assert composite <= covered, (
            f"composite foreign keys without a test: {sorted(composite - covered)}"
        )


@pytest.mark.asyncio
async def test_a_valid_same_workspace_reference_is_accepted(stack: Stack) -> None:
    org = await world.create_org(stack)
    ws = await world.create_workspace(stack, org)
    matter = await world.create_matter(stack, ws)
    doc = await world.add_document(
        stack, ws, ws.admin, ContextRole.ADMIN, visibility="matter", matter=matter
    )
    assert doc is not None
