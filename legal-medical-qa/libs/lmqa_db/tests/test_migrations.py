"""G1.1 migrations and G1.2 role and table audit, against a real PostgreSQL."""

from __future__ import annotations

import psycopg
import pytest

from lmqa_db import LOGIN_ROLES
from lmqa_db.bootstrap import with_database
from lmqa_testing.pg import fresh_database, migrate, role_dsn, superuser_dsn

pytestmark = [pytest.mark.integration, pytest.mark.stage1]

HELPER_ROLES = ("policy_helper", "principal_owner", "audit_definer", "scope_maintainer")
CONTENT_TABLES = ("documents", "document_versions", "chunks", "doc_keys", "retrieval_records")
AUDIT_TABLES = ("audit_event", "audit_payload")


def _admin(dbname: str) -> psycopg.Connection:
    return psycopg.connect(with_database(superuser_dsn(), dbname), autocommit=True)


def _fingerprint(dbname: str) -> dict[str, list[tuple[object, ...]]]:
    queries = {
        "columns": (
            "SELECT table_name, column_name, data_type, is_nullable, column_default"
            " FROM information_schema.columns WHERE table_schema = 'public' ORDER BY 1, 2"
        ),
        "policies": (
            "SELECT tablename, policyname, cmd, roles::text, qual, with_check"
            " FROM pg_policies WHERE schemaname = 'public' ORDER BY 1, 2"
        ),
        "functions": (
            "SELECT p.proname, pg_get_userbyid(p.proowner), p.prosecdef"
            " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public' ORDER BY 1, 2"
        ),
        "triggers": (
            "SELECT event_object_table, trigger_name FROM information_schema.triggers"
            " WHERE trigger_schema = 'public' ORDER BY 1, 2"
        ),
    }
    with _admin(dbname) as conn:
        return {name: conn.execute(q).fetchall() for name, q in queries.items()}  # type: ignore[arg-type]


def test_g1_1_apply_rollback_apply_gives_identical_schema() -> None:
    name = "lmqa_roundtrip"
    fresh_database(name)
    before = _fingerprint(name)
    assert before["policies"], "policies must exist"
    migrate(name, "base", downgrade=True)
    with _admin(name) as conn:
        left = conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()
        assert left is not None
        assert left[0] == 0, "rollback must remove every table"
    migrate(name)
    assert _fingerprint(name) == before


def test_g1_1_rollback_on_a_populated_database() -> None:
    name = "lmqa_roundtrip_populated"
    fresh_database(name)
    with _admin(name) as conn:
        conn.execute("INSERT INTO orgs (name, deployment_type) VALUES ('populated', 'legal')")
    migrate(name, "base", downgrade=True)
    migrate(name)
    with _admin(name) as conn:
        row = conn.execute("SELECT count(*) FROM orgs").fetchone()
        assert row is not None
        assert row[0] == 0


def test_g1_2_service_roles_are_not_owners_and_do_not_bypass_rls(migrated_db: str) -> None:
    with _admin(migrated_db) as conn:
        rows = conn.execute(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s)",
            (list(LOGIN_ROLES) + list(HELPER_ROLES),),
        ).fetchall()
        assert {r[0] for r in rows} == set(LOGIN_ROLES) | set(HELPER_ROLES)
        for name, superuser, bypass in rows:
            assert not superuser, name
            assert not bypass, name
        owned = conn.execute(
            "SELECT tableowner, count(*) FROM pg_tables WHERE schemaname = 'public'"
            " AND tablename NOT LIKE 'sm\\_%%' GROUP BY 1"
        ).fetchall()
        assert owned == [("lmqa_owner", owned[0][1])]
        functions = conn.execute(
            "SELECT DISTINCT pg_get_userbyid(p.proowner) FROM pg_proc p"
            " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'"
        ).fetchall()
        service_owned = {f[0] for f in functions} & set(LOGIN_ROLES)
        assert not service_owned, "no login service role may own a function"


def test_g1_2_every_table_has_forced_row_level_security(migrated_db: str) -> None:
    with _admin(migrated_db) as conn:
        weak = conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname NOT LIKE 'sm\\_%%'"
            " AND NOT (c.relrowsecurity AND c.relforcerowsecurity)"
        ).fetchall()
        assert weak == []


def test_g1_2_no_public_grants(migrated_db: str) -> None:
    with _admin(migrated_db) as conn:
        tables = conn.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = 'PUBLIC' AND table_schema = 'public'"
        ).fetchall()
        routines = conn.execute(
            "SELECT routine_name FROM information_schema.routine_privileges"
            " WHERE grantee = 'PUBLIC' AND routine_schema = 'public'"
        ).fetchall()
        assert tables == []
        assert routines == []


def test_g1_2_services_hold_only_the_privileges_the_design_gives_them(migrated_db: str) -> None:
    with _admin(migrated_db) as conn:

        def can(role: str, table: str, priv: str = "SELECT") -> bool:
            row = conn.execute(
                "SELECT has_table_privilege(%s, %s, %s)", (role, f"public.{table}", priv)
            ).fetchone()
            assert row is not None
            return bool(row[0])

        every_table = [
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                " AND tablename NOT LIKE 'sm\\_%%'"
            ).fetchall()
        ]
        # The Gateway reads principal_v and nothing else (doc 4.2, 10.3).
        assert can("svc_gateway", "principal_v")
        assert [t for t in every_table if can("svc_gateway", t)] == []
        # Identity has no access to content or audit payloads (doc 10.3).
        for table in (*CONTENT_TABLES, *AUDIT_TABLES, "chunks"):
            assert not can("svc_identity", table), table
        # Generation and the validator cannot write the ledger (G5.10).
        for role in ("svc_generation", "svc_validator", "svc_ingestion"):
            assert not can(role, "retrieval_records", "INSERT"), role
        assert can("svc_retrieval", "retrieval_records", "INSERT")
        assert not can("svc_retrieval", "retrieval_records", "UPDATE")
        assert not can("svc_retrieval", "retrieval_records", "DELETE")
        # Nobody holds write access to audit tables; audit_append is the only writer (doc 13.3).
        for role in (*LOGIN_ROLES, "scope_maintainer", "policy_helper"):
            for table in (*AUDIT_TABLES, "audit_anchor"):
                for priv in ("UPDATE", "DELETE", "TRUNCATE"):
                    assert not can(role, table, priv), (role, table, priv)
        for role in LOGIN_ROLES:
            assert not can(role, "audit_event", "INSERT"), role
        # Only the audit reader may read audit payloads or private keys.
        for role in LOGIN_ROLES:
            assert can(role, "audit_payload") == (role == "svc_audit_reader"), role
        # The reconciler sees no text columns (doc 10.3).
        row = conn.execute(
            "SELECT has_column_privilege('svc_reconciler', 'public.chunks', 'text_ciphertext', 'SELECT')"
        ).fetchone()
        assert row is not None
        assert not row[0]
        row = conn.execute(
            "SELECT has_column_privilege('svc_reconciler', 'public.chunks', 'id', 'SELECT')"
        ).fetchone()
        assert row is not None
        assert row[0]


def test_g1_2_service_roles_can_connect_with_their_own_login(migrated_db: str) -> None:
    for role in LOGIN_ROLES:
        with psycopg.connect(role_dsn(role, migrated_db)) as conn:
            row = conn.execute("SELECT current_user").fetchone()
            assert row is not None
            assert row[0] == role
