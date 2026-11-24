-- The Super Admin policy set (blueprint 5.3, 16.3; R-3 criteria 3 and 4, R-79 criterion 2). Re-applied on every
-- migrate. When the transaction context is an active Super Admin, svc_identity's identity_all policies are off
-- (15_force_rls.sql) and only these rows are reachable, whichever identity code path runs:
--   organizations, join_codes, workspaces (metadata) and governance_requests of the governed organization;
--   memberships of admins, of Super Admins and co-owners, and the caller's own;
--   workspace_usage of the organization's workspaces;
--   users: the caller's own row and the organization's admins (names for the approval list).
-- Content tables carry no svc_identity grant at all, so documents, chunks, tenant memberships, walls and audit
-- payloads return nothing. Organization-scope audit events are written through audit_append only.

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'svc_identity') then
        return;
    end if;
    drop policy if exists super_admin_org on organizations;
    create policy super_admin_org on organizations for all to svc_identity
        using (id = (select app_super_admin_org())) with check (id = (select app_super_admin_org()));
    drop policy if exists super_admin_codes on join_codes;
    create policy super_admin_codes on join_codes for all to svc_identity
        using (org_id = (select app_super_admin_org())) with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_workspaces on workspaces;
    create policy super_admin_workspaces on workspaces for all to svc_identity
        using (org_id = (select app_super_admin_org())) with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_memberships on memberships;
    create policy super_admin_memberships on memberships for all to svc_identity
        using (org_id = (select app_super_admin_org())
               and (role in ('admin', 'super_admin') or co_owner or user_id = (select app_user_id())))
        with check (org_id = (select app_super_admin_org())
                    and (role in ('admin', 'super_admin') or co_owner or user_id = (select app_user_id())));
    drop policy if exists super_admin_governance on governance_requests;
    create policy super_admin_governance on governance_requests for all to svc_identity
        using (org_id = (select app_super_admin_org())) with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_usage on workspace_usage;
    create policy super_admin_usage on workspace_usage for select to svc_identity
        using (workspace_id in (select w.id from workspaces w where w.org_id = (select app_super_admin_org())));
    drop policy if exists super_admin_users on users;
    create policy super_admin_users on users for select to svc_identity
        using ((select app_super_admin_org()) is not null
               and (id = (select app_user_id())
                    or id in (select m.user_id from memberships m where m.role = 'admin')));
    -- Keys: approving an admin activates their workspace, which needs its content key; the organization's control
    -- chain needs its audit keys. Insert and read only; key rows of content (doc_keys, cache_keys) stay out.
    drop policy if exists super_admin_org_keys on org_keys;
    create policy super_admin_org_keys on org_keys for select to svc_identity
        using (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_org_keys_insert on org_keys;
    create policy super_admin_org_keys_insert on org_keys for insert to svc_identity
        with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_workspace_keys on workspace_keys;
    create policy super_admin_workspace_keys on workspace_keys for select to svc_identity
        using (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_workspace_keys_insert on workspace_keys;
    create policy super_admin_workspace_keys_insert on workspace_keys for insert to svc_identity
        with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_audit_keys on audit_keys;
    create policy super_admin_audit_keys on audit_keys for select to svc_identity
        using (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_audit_keys_insert on audit_keys;
    create policy super_admin_audit_keys_insert on audit_keys for insert to svc_identity
        with check (org_id = (select app_super_admin_org()));
    drop policy if exists super_admin_self on users;
    create policy super_admin_self on users for update to svc_identity
        using (id = (select app_user_id())) with check (id = (select app_user_id()));
end
$$;
