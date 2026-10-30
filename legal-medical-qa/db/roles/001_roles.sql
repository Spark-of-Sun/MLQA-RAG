-- Role and grant definitions (doc 10.3, 16.3, 9.2).
-- Service roles are non-owners with NOBYPASSRLS. Passwords are set out of band by
-- tools/set_role_passwords.py from the PG_DSN_* values; none appear in this file.

DO $$
DECLARE r text;
BEGIN
  -- Non-login helper roles: they own SECURITY DEFINER functions / the principal view.
  FOREACH r IN ARRAY ARRAY['policy_helper', 'principal_owner', 'audit_definer', 'scope_maintainer'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOBYPASSRLS NOSUPERUSER', r);
    END IF;
  END LOOP;

  -- Login service roles, one per service.
  FOREACH r IN ARRAY ARRAY[
    'svc_gateway', 'svc_identity', 'svc_ingestion', 'svc_retrieval', 'svc_generation',
    'svc_validator', 'svc_audit_reader', 'svc_reconciler', 'svc_ops', 'ops_metadata_ro'
  ] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format(
        'CREATE ROLE %I LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
    END IF;
  END LOOP;
END
$$;

-- Migration owner: owns every table. No service holds this role (doc 10.3).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lmqa_owner') THEN
    CREATE ROLE lmqa_owner LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;
-- The owner must be a member of the helper roles to hand them function ownership.
GRANT policy_helper, principal_owner, audit_definer, scope_maintainer TO lmqa_owner;


-- PgBouncer authenticates each client as itself (doc 10.3): it looks the SCRAM verifier up through
-- one narrow function, so the pooler never needs a superuser and holds no password list of its own.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgbouncer_auth') THEN
    CREATE ROLE pgbouncer_auth LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;
