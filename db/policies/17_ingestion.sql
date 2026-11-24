-- svc_ingestion acts as the uploader (blueprint 5.4, 8; DEV-13). A job carries only a document id, so two narrow
-- SECURITY DEFINER helpers (owned by policy_helper, 95_helper_owner.sql) give the worker what it cannot read under
-- RLS: the ids of documents still processing, and the uploader of one such document. Everything else the worker
-- does runs under scoped(pool, Claims(user_id=<uploader>)) and these policies.

create or replace function app_ingest_pending() returns setof uuid
    language sql stable security definer set search_path = public, pg_temp
as $$ select d.id from documents d where d.status = 'processing' order by d.created_at $$;

create or replace function app_ingest_principal(p_document uuid) returns uuid
    language sql stable security definer set search_path = public, pg_temp
as $$ select d.owner_id from documents d where d.id = p_document and d.status = 'processing' $$;

-- People labels for the document library: the encrypted name and email (lmqa_keys.FieldCipher opens them) and the
-- workspace role of each listed user, only for users who belong to the caller's active workspace.
create or replace function app_workspace_people(p_users uuid[])
    returns table (id uuid, name_ct bytea, email_ct bytea, role text)
    language sql stable security definer set search_path = public, pg_temp
as $$
    select u.id, u.name_ct, u.email_ct, m.role
    from users u
    join memberships m on m.user_id = u.id and m.workspace_id = app_active_workspace() and m.status <> 'rejected'
    where u.id = any(p_users)
$$;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'svc_ingestion') then
        return;
    end if;
    drop policy if exists ingest_update on documents;
    create policy ingest_update on documents for update to svc_ingestion
        using (workspace_id = (select app_active_workspace()) and owner_id = (select app_user_id()))
        with check (workspace_id = (select app_active_workspace()) and owner_id = (select app_user_id()));
    drop policy if exists ingest_delete on chunks;
    create policy ingest_delete on chunks for delete to svc_ingestion
        using (workspace_id = (select app_active_workspace()) and owner_id = (select app_user_id()));
    drop policy if exists ingest_cache on embedding_cache;
    create policy ingest_cache on embedding_cache for all to svc_ingestion
        using (org_id = (select app_active_org())) with check (org_id = (select app_active_org()));
end
$$;
