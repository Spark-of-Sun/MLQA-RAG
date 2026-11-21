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
