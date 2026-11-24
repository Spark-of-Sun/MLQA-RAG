-- FORCE ROW LEVEL SECURITY on every table (blueprint 10.3, 16.1, G1.2). Re-applied on every migrate, so a table
-- added later cannot be left without it. Content tables get their policies in 20_rls.sql; control-plane tables are
-- reachable only by the roles below, never by a data-plane role.
--
--   lmqa_owner       definer of the audit and trigger functions; reads the control tables through these policies;
--                    it never logs in at runtime
--   policy_helper    NOLOGIN definer of the STABLE lookup helpers (95_helper_owner.sql, DEV-48); select only
--   svc_identity     control plane: organizations, workspaces, memberships, codes, governance, matters, grants;
--                    when the context is a Super Admin only the 16_super_admin.sql set applies (R-3 criterion 3)
--   svc_ops          operator plane: ops schema and governance requests
--   svc_reconciler   index metadata only (column grants in db/roles/grants.sql)
-- No runtime role bypasses RLS: lmqa_system is retired (DEV-13); the boot self-test fails if any login role can.

do $$
declare
    t record;
begin
    for t in
        select n.nspname, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where c.relkind in ('r', 'p') and n.nspname in ('public', 'ops') and c.relname <> 'schema_migrations'
          and c.relname not like 'procrastinate%'
    loop
        execute format('alter table %I.%I enable row level security', t.nspname, t.relname);
        execute format('alter table %I.%I force row level security', t.nspname, t.relname);
    end loop;
end
$$;

do $$
declare
    tbl text;
    control text[] := array[
        'users', 'organizations', 'workspaces', 'memberships', 'join_codes', 'join_attempts', 'matters',
        'matter_grants', 'matter_walls', 'access_exceptions', 'break_glass_sessions', 'governance_requests',
        'governance_approvals', 'org_keys', 'workspace_keys', 'quotas', 'workspace_usage', 'idempotency_keys',
        'embedding_cache', 'index_outbox', 'deletion_tombstones', 'doc_keys', 'audit_keys', 'audit_checkpoints',
        'audit_anchors', 'document_versions', 'audit_events', 'provisioning_sagas', 'notifications',
        'review_tasks', 'alerts', 'step_up_events', 'auth0_role_snapshots', 'platform_keys', 'cache_keys',
        'audit_chains', 'audit_payloads'];
    definer_reads text[] := array[
        'users', 'organizations', 'workspaces', 'memberships', 'matters', 'matter_grants', 'matter_walls',
        'access_exceptions', 'break_glass_sessions', 'audit_events', 'audit_checkpoints', 'audit_anchors',
        'audit_keys', 'workspace_usage', 'index_outbox', 'deletion_tombstones', 'audit_chains', 'audit_payloads'];
    identity_tables text[] := array[
        'users', 'organizations', 'workspaces', 'memberships', 'join_codes', 'join_attempts', 'matters',
        'matter_grants', 'matter_walls', 'access_exceptions', 'break_glass_sessions', 'governance_requests',
        'governance_approvals', 'org_keys', 'workspace_keys', 'quotas', 'workspace_usage', 'audit_keys',
        'provisioning_sagas', 'notifications', 'review_tasks', 'alerts', 'step_up_events', 'auth0_role_snapshots'];
begin
    foreach tbl in array control loop
        execute format('drop policy if exists owner_definer on %I', tbl);
        execute format('drop policy if exists identity_all on %I', tbl);
        execute format('drop policy if exists system_all on %I', tbl);
        execute format('drop policy if exists helper_read on %I', tbl);
    end loop;
    foreach tbl in array definer_reads loop
        execute format('create policy owner_definer on %I for all to lmqa_owner using (true) with check (true)', tbl);
    end loop;
    if exists (select 1 from pg_roles where rolname = 'svc_identity') then
        foreach tbl in array identity_tables loop
            execute format('create policy identity_all on %I for all to svc_identity '
                           'using ((select app_super_admin_org()) is null) '
                           'with check ((select app_super_admin_org()) is null)', tbl);
        end loop;
    end if;
end
$$;

-- Keys, outbox and tombstones: written by the data-plane services for their own workspace only.
drop policy if exists doc_keys_scoped on doc_keys;
create policy doc_keys_scoped on doc_keys for all
    using (workspace_id = (select app_active_workspace()))
    with check (workspace_id = (select app_active_workspace()));
drop policy if exists workspace_keys_scoped on workspace_keys;
create policy workspace_keys_scoped on workspace_keys for select
    using (workspace_id = (select app_active_workspace()));
drop policy if exists org_keys_scoped on org_keys;
-- The caller's active organization through the definer helper: data-plane roles hold no grant on memberships.
create policy org_keys_scoped on org_keys for select
    using (org_id = (select app_active_org()));
drop policy if exists cache_keys_scoped on cache_keys;
create policy cache_keys_scoped on cache_keys for all
    using (workspace_id = (select app_active_workspace()))
    with check (workspace_id = (select app_active_workspace()));
-- Platform keys (user contact fields, blind index): read by the services that show people, created by identity.
-- They are not organization data, so the Super Admin context does not narrow them (16_super_admin.sql).
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'svc_identity') then
        execute 'drop policy if exists platform_identity on platform_keys';
        execute 'create policy platform_identity on platform_keys for all to svc_identity using (true) with check (true)';
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_ingestion') then
        execute 'drop policy if exists platform_ingestion on platform_keys';
        execute 'create policy platform_ingestion on platform_keys for select to svc_ingestion using (true)';
    end if;
end
$$;
drop policy if exists outbox_scoped on index_outbox;
create policy outbox_scoped on index_outbox for insert
    with check (workspace_id = (select app_active_workspace()));
drop policy if exists tombstones_scoped on deletion_tombstones;
create policy tombstones_scoped on deletion_tombstones for insert
    with check (workspace_id = (select app_active_workspace()));
drop policy if exists versions_scoped on document_versions;
create policy versions_scoped on document_versions for all
    using (workspace_id = (select app_active_workspace()))
    with check (workspace_id = (select app_active_workspace()));
drop policy if exists idempotency_own on idempotency_keys;
create policy idempotency_own on idempotency_keys for all
    using (user_id = (select app_user_id())) with check (user_id = (select app_user_id()));

-- The outbox trigger (owner, SECURITY DEFINER) keeps chunk visibility columns equal to their document's.
drop policy if exists chunks_owner_sync on chunks;
create policy chunks_owner_sync on chunks for update to lmqa_owner using (true) with check (true);
drop policy if exists chunks_owner_read on chunks;
create policy chunks_owner_read on chunks for select to lmqa_owner using (true);
drop policy if exists versions_owner on document_versions;
create policy versions_owner on document_versions for all to lmqa_owner using (true) with check (true);

-- Chunks are written by the ingestion worker acting as the uploader (the job envelope carries the principal).
drop policy if exists chunks_insert on chunks;
create policy chunks_insert on chunks for insert with check (
    workspace_id = (select app_active_workspace()) and owner_id = (select app_user_id())
);

-- The reconciler compares index metadata across all workspaces; it holds column grants on IDs only.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'svc_reconciler') then
        execute 'drop policy if exists reconciler_meta on chunks';
        execute 'create policy reconciler_meta on chunks for select to svc_reconciler using (true)';
        execute 'drop policy if exists reconciler_meta on documents';
        execute 'create policy reconciler_meta on documents for select to svc_reconciler using (true)';
        execute 'drop policy if exists reconciler_outbox on index_outbox';
        execute 'create policy reconciler_outbox on index_outbox for all to svc_reconciler using (true) with check (true)';
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_ops') then
        execute 'drop policy if exists ops_all on ops.operator_accounts';
        execute 'create policy ops_all on ops.operator_accounts for all to svc_ops using (true) with check (true)';
        execute 'drop policy if exists ops_all on ops.operator_access_grants';
        execute 'create policy ops_all on ops.operator_access_grants for all to svc_ops using (true) with check (true)';
        execute 'drop policy if exists ops_all on ops.security_holds';
        execute 'create policy ops_all on ops.security_holds for all to svc_ops using (true) with check (true)';
        execute 'drop policy if exists ops_governance on governance_requests';
        execute 'create policy ops_governance on governance_requests for all to svc_ops using (true) with check (true)';
        execute 'drop policy if exists ops_governance on governance_approvals';
        execute 'create policy ops_governance on governance_approvals for all to svc_ops using (true) with check (true)';
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_audit_reader') then
        execute 'drop policy if exists audit_reader on audit_events';
        execute 'create policy audit_reader on audit_events for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on audit_chains';
        execute 'create policy audit_reader on audit_chains for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on audit_payloads';
        execute 'create policy audit_reader on audit_payloads for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on audit_keys';
        execute 'create policy audit_reader on audit_keys for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on org_keys';
        execute 'create policy audit_reader on org_keys for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on platform_keys';
        execute 'create policy audit_reader on platform_keys for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on users';
        execute 'create policy audit_reader on users for select to svc_audit_reader using (true)';
        execute 'drop policy if exists audit_reader on audit_checkpoints';
        execute 'create policy audit_reader on audit_checkpoints for all to svc_audit_reader using (true) with check (true)';
        execute 'drop policy if exists audit_reader on audit_anchors';
        execute 'create policy audit_reader on audit_anchors for all to svc_audit_reader using (true) with check (true)';
    end if;
    if exists (select 1 from pg_roles where rolname = 'ops_metadata_ro') then
        execute 'drop policy if exists ops_meta on ops.operator_access_grants';
        execute 'create policy ops_meta on ops.operator_access_grants for select to ops_metadata_ro using (true)';
        execute 'drop policy if exists ops_meta_usage on workspace_usage';
        execute 'create policy ops_meta_usage on workspace_usage for select to ops_metadata_ro using (true)';
    end if;
end
$$;

-- Boot self-test (10.3, G1.3): every service calls this at start and refuses to run unless it returns no rows.
create or replace function app_boot_self_test() returns table (problem text)
    language sql stable security definer set search_path = public, pg_temp
as $$
    select format('table %I.%I has no FORCE ROW LEVEL SECURITY', n.nspname, c.relname)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where c.relkind in ('r', 'p') and n.nspname in ('public', 'ops') and c.relname <> 'schema_migrations'
      and c.relname not like 'procrastinate%' and not (c.relrowsecurity and c.relforcerowsecurity)
    union all
    select format('role %I can bypass row-level security or owns tables', r.rolname)
    from pg_roles r
    where (r.rolname like 'svc\_%' or r.rolname in ('lmqa_app', 'ops_metadata_ro'))
      and (r.rolbypassrls or r.rolsuper
           or exists (select 1 from pg_class c where c.relowner = r.oid and c.relkind in ('r', 'p')))
    union all
    select format('login role %I can bypass row-level security', r.rolname)
    from pg_roles r
    where r.rolcanlogin and r.rolbypassrls and not r.rolsuper
    union all
    select 'policy_helper can log in' from pg_roles r where r.rolname = 'policy_helper' and r.rolcanlogin
    union all
    select format('PUBLIC holds %s on %I', p.privilege_type, p.table_name)
    from information_schema.role_table_grants p
    where p.grantee = 'PUBLIC' and p.table_schema in ('public', 'ops')
$$;
