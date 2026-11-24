-- Access-decision helpers (blueprint 5.4, 10.3). Re-applied on every migrate.

-- The caller, from the transaction-local setting written by lmqa_db.Database.scoped().
-- No setting -> NULL -> every policy below is false -> zero rows (fail closed, G1.3).
create or replace function app_user_id() returns uuid
    language sql stable
as $$ select nullif(current_setting('app.user_id', true), '')::uuid $$;

-- Rule 1: the membership, the workspace and the organization must all be active, else NULL.
-- Only admins and tenants have a workspace; the Super Admin never reaches content (blueprint 5.3).
create or replace function app_active_workspace() returns uuid
    language sql stable security definer set search_path = public, pg_temp
as $$
    select m.workspace_id
    from memberships m
    join workspaces w on w.id = m.workspace_id
    join organizations o on o.id = m.org_id
    where m.user_id = app_user_id() and m.status = 'active' and w.status = 'active'
      and o.status = 'active' and m.role in ('admin', 'tenant')
    limit 1
$$;

create or replace function app_active_role() returns text
    language sql stable security definer set search_path = public, pg_temp
as $$
    select m.role
    from memberships m
    join workspaces w on w.id = m.workspace_id
    join organizations o on o.id = m.org_id
    where m.user_id = app_user_id() and m.status = 'active' and w.status = 'active'
      and o.status = 'active' and m.role in ('admin', 'tenant')
    limit 1
$$;

-- Who the caller may share a document with: an active member of the caller's own active workspace, other than the
-- caller. A member may share only with the workspace admin; the admin may share with any member.
create or replace function app_share_target_ok(p_target uuid) returns boolean
    language sql stable security definer set search_path = public, pg_temp
as $$
    select exists (
        select 1
        from memberships t
        where t.user_id = p_target and t.user_id <> app_user_id() and t.status = 'active'
          and t.workspace_id = app_active_workspace()
          and (t.role = 'admin' or app_active_role() = 'admin')
    )
$$;

-- The caller owns this document in their active workspace. A function, so that the document_shares insert policy
-- does not expand the documents policies (which read document_shares) inside its own plan: no policy recursion.
create or replace function app_owns_document(p_document uuid) returns boolean
    language sql stable security definer set search_path = public, pg_temp
as $$
    select exists (
        select 1 from documents d
        where d.id = p_document and d.owner_id = app_user_id() and d.workspace_id = app_active_workspace()
    )
$$;

-- The organization the caller governs as Super Admin (blueprint 5.3), else NULL. A Super Admin context switches
-- svc_identity from its control-plane policies to the restricted set in 16_super_admin.sql (R-3 criterion 3).
create or replace function app_super_admin_org() returns uuid
    language sql stable security definer set search_path = public, pg_temp
as $$
    select m.org_id from memberships m
    where m.user_id = app_user_id() and m.role = 'super_admin' and m.status = 'active'
    limit 1
$$;

-- The organization of the caller's active workspace (embedding cache scope for svc_ingestion).
create or replace function app_active_org() returns uuid
    language sql stable security definer set search_path = public, pg_temp
as $$ select w.org_id from workspaces w where w.id = app_active_workspace() $$;
