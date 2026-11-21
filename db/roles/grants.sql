-- Least-privilege grants (blueprint 9.2, 10.3, G1.2). Re-applied on every migrate.
-- Roles themselves are created by libs/lmqa_db/migrate.py (they need passwords from settings):
--   lmqa_owner (schema owner, migrations only), lmqa_app (NOBYPASSRLS), lmqa_system (BYPASSRLS).

revoke all on all tables in schema public from public;
revoke all on function app_active_workspace(), app_active_role(), audit_verify(uuid),
    audit_append(uuid, uuid, uuid, text, text, text, jsonb) from public;
grant usage on schema public to lmqa_app, lmqa_system;

-- lmqa_app: the data plane. Content tables only, always under row-level security.
revoke all on all tables in schema public from lmqa_app;
grant select, insert, delete on documents to lmqa_app;
grant select on chunks to lmqa_app;
grant select, insert on queries, retrieval_records to lmqa_app;

-- lmqa_system: identity, onboarding and the ingestion worker. Authorization is enforced in code.
revoke all on all tables in schema public from lmqa_system;
grant select, insert, update, delete on users, organizations, workspaces, memberships, join_codes,
    documents, chunks to lmqa_system;
grant select on queries, audit_events to lmqa_system;

grant execute on function app_user_id(), app_active_workspace(), app_active_role() to lmqa_app, lmqa_system;
grant execute on function audit_append(uuid, uuid, uuid, text, text, text, jsonb) to lmqa_app, lmqa_system;
grant execute on function audit_material(uuid, uuid, uuid, text, text, text, jsonb, timestamptz, text)
    to lmqa_app, lmqa_system;
grant execute on function audit_verify(uuid) to lmqa_system;
