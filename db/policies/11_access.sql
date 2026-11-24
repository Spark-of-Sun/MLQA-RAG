-- The access decision (blueprint 5.4). One function, used by every content policy; the vector filter builder
-- (lmqa_vectorstore.filters) and the Python oracle (lmqa_testing.oracle) implement exactly the same order, and G1.4
-- proves the three agree on random inputs. A rule earlier in the list wins over every later rule.
--
--   1 membership, workspace or organization not active               -> deny  (app_active_workspace() is NULL)
--   2 a live wall exists for (user, document's matter)                -> deny  (beats ownership, role, grants)
--   3 the document is the user's own                                  -> allow
--   4 admin and visibility 'matter'                                   -> allow (all tiers)
--   5 tenant, 'matter', unexpired grant with max_tier >= tier         -> allow
--   6 tenant, 'matter', active emergency exception, workspace opted in,
--     tier <= exception cap (never tier 4)                            -> allow (read and query only)
--   7 admin, 'private', admin_can_read_private and an active
--     break-glass session                                             -> allow (read and query only)
--   8 anything else                                                   -> deny
--
-- These eight rules are the whole decision (KD-3, R-4.1). The MVP rules 7a (visibility 'workspace') and 7b
-- (document_shares) were migrated out in db/migrations/0011_access_rules.sql (DEV-14, pending Q-05 and Q-37):
-- nothing below reads document_shares, and the visibility CHECK allows only 'private' and 'matter'.
--
-- The operation (read, query, export) comes from the transaction-local setting app.operation, default 'read'. An
-- unknown operation is denied. Rules 6 and 7 allow read and query only, so an export context gets no rows from them.
--
-- Helpers are SECURITY DEFINER so they can read grants, walls and sessions, which callers cannot read directly; each
-- one keys on app_user_id(), never on an argument naming another user.

create or replace function app_operation() returns text
    language sql stable
as $$ select coalesce(nullif(current_setting('app.operation', true), ''), 'read') $$;

create or replace function app_walled(p_matter uuid) returns boolean
    language sql stable security definer set search_path = public, pg_temp
as $$
    select p_matter is not null and exists (
        select 1 from matter_walls w
        where w.matter_id = p_matter and w.user_id = app_user_id()
          and w.lifted_at is null and w.effective_from <= now()
    )
$$;

create or replace function app_grant_tier(p_matter uuid) returns smallint
    language sql stable security definer set search_path = public, pg_temp
as $$
    select max(g.max_tier)::smallint from matter_grants g
    where g.matter_id = p_matter and g.user_id = app_user_id() and g.workspace_id = app_active_workspace()
      and (g.expires_at is null or g.expires_at > now())
$$;

create or replace function app_emergency_cap(p_matter uuid) returns smallint
    language sql stable security definer set search_path = public, pg_temp
as $$
    select max(e.tier_cap)::smallint
    from access_exceptions e
    join workspaces w on w.id = e.workspace_id
    join organizations o on o.id = w.org_id
    where e.matter_id = p_matter and e.user_id = app_user_id() and e.workspace_id = app_active_workspace()
      and e.state = 'active' and e.expires_at > now()
      and w.emergency_access and o.kind in ('medical', 'both')
$$;

create or replace function app_break_glass_active() returns boolean
    language sql stable security definer set search_path = public, pg_temp
as $$
    select exists (
        select 1 from break_glass_sessions b
        join workspaces w on w.id = b.workspace_id
        where b.admin_user_id = app_user_id() and b.workspace_id = app_active_workspace()
          and b.state = 'active' and b.expires_at > now() and w.admin_can_read_private
    )
$$;

-- Rule 7b (named shares) is no longer part of the decision; its helper is gone with it.
drop function if exists app_shared_with_me(uuid);

create or replace function app_principal_version() returns bigint
    language sql stable security definer set search_path = public, pg_temp
as $$
    select m.principal_version from memberships m
    where m.user_id = app_user_id() and m.status in ('pending_approval', 'active', 'suspended') limit 1
$$;

-- The single decision. Arguments are the row's own columns, so the planner evaluates it per row without joins in
-- the policy itself; the helpers are STABLE and keyed on the caller. p_document is unused since rule 7b left the
-- decision; it stays in the signature so policies and grants keep one stable function.
create or replace function app_can_read(
    p_workspace uuid, p_owner uuid, p_visibility text, p_matter uuid, p_tier smallint, p_document uuid
) returns boolean
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    ws      uuid := app_active_workspace();
    op      text := app_operation();
    limited boolean;                                                      -- rules 6 and 7 allow these only
    role    text;
    cap     smallint;
begin
    if op not in ('read', 'query', 'export') then                         -- unknown operation: fail closed
        return false;
    end if;
    limited := op in ('read', 'query');
    if ws is null or p_workspace is distinct from ws then                 -- rule 1
        return false;
    end if;
    if app_walled(p_matter) then                                          -- rule 2
        return false;
    end if;
    if p_owner = app_user_id() then                                       -- rule 3
        return true;
    end if;
    role := app_active_role();
    if p_visibility = 'matter' and p_matter is not null then
        if role = 'admin' then                                            -- rule 4
            return true;
        end if;
        if role = 'tenant' then
            cap := app_grant_tier(p_matter);
            if cap is not null and cap >= p_tier then                     -- rule 5
                return true;
            end if;
            cap := app_emergency_cap(p_matter);
            if cap is not null and p_tier <= least(cap, 3) then           -- rule 6
                return limited;
            end if;
        end if;
        return false;                                                     -- rule 8
    end if;
    if p_visibility = 'private' and role = 'admin' and app_break_glass_active() then   -- rule 7
        return limited;
    end if;
    return false;                                                         -- rule 8
end
$$;

-- Why a row was allowed, for audit severity (rule 6 and 7 reads are flagged break_glass). NULL when denied.
create or replace function app_access_basis(
    p_workspace uuid, p_owner uuid, p_visibility text, p_matter uuid, p_tier smallint, p_document uuid
) returns text
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    role text := app_active_role();
    cap  smallint;
begin
    if not app_can_read(p_workspace, p_owner, p_visibility, p_matter, p_tier, p_document) then
        return null;
    end if;
    if p_owner = app_user_id() then return 'owner'; end if;
    if p_visibility = 'matter' and role = 'admin' then return 'admin_matter'; end if;
    if p_visibility = 'matter' then
        cap := app_grant_tier(p_matter);
        return case when cap is not null and cap >= p_tier then 'grant' else 'emergency' end;
    end if;
    return 'break_glass';
end
$$;

-- The upload tier ceiling (5.5, R-5.3): the highest tier the caller may give a new document. Admin on a matter and
-- anyone on a private document (no matter) may use tier 4 (Q-28); a tenant on a matter is capped by an unexpired
-- grant's max_tier, and without one may not upload to the matter at all. An emergency exception never allows an
-- upload. NULL means no upload.
create or replace function app_upload_ceiling(p_visibility text, p_matter uuid) returns smallint
    language sql stable security definer set search_path = public, pg_temp
as $$
    select case
        when app_active_workspace() is null or app_walled(p_matter) then null
        when p_visibility = 'private' and p_matter is null then 4::smallint
        when p_visibility = 'matter' and p_matter is not null and app_active_role() = 'admin' then 4::smallint
        when p_visibility = 'matter' and p_matter is not null and app_active_role() = 'tenant'
            then app_grant_tier(p_matter)
    end
$$;

-- Scope hash (16.2, 10.7): what the caller can see, as one digest that keys caches and is recorded in the ledger.
-- Recomputed by triggers whenever grants, walls, exceptions, sessions or workspace flags change.
create or replace function app_compute_scope_hash(p_user uuid) returns text
    language sql stable security definer set search_path = public, pg_temp
as $$
    select encode(sha256(convert_to(concat_ws('|',
        (select string_agg(m.workspace_id::text || ':' || m.role || ':' || m.status, ',') from memberships m
            where m.user_id = p_user),
        (select string_agg(g.matter_id::text || ':' || g.max_tier || ':' || coalesce(g.expires_at::text, ''), ','
                           order by g.matter_id) from matter_grants g where g.user_id = p_user),
        (select string_agg(w.matter_id::text, ',' order by w.matter_id) from matter_walls w
            where w.user_id = p_user and w.lifted_at is null),
        (select string_agg(e.id::text || ':' || e.state, ',' order by e.id) from access_exceptions e
            where e.user_id = p_user and e.state = 'active'),
        (select string_agg(b.id::text || ':' || b.state, ',' order by b.id) from break_glass_sessions b
            where b.admin_user_id = p_user and b.state = 'active'),
        (select string_agg(w.id::text || ':' || w.admin_can_read_private || ':' || w.emergency_access, ',')
            from workspaces w join memberships m on m.workspace_id = w.id where m.user_id = p_user)
    ), 'UTF8')), 'hex')
$$;

create or replace function app_bump_scope(p_user uuid) returns void
    language sql volatile security definer set search_path = public, pg_temp
as $$
    update memberships
       set scope_version = scope_version + 1, scope_hash = app_compute_scope_hash(p_user)
     where user_id = p_user;
    select pg_notify('lmqa_scope', p_user::text);
$$;

create or replace function app_scope_trigger() returns trigger
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    affected uuid;
begin
    if tg_table_name = 'break_glass_sessions' then
        affected := coalesce(new.admin_user_id, old.admin_user_id);
    elsif tg_table_name = 'workspaces' then
        perform app_bump_scope(m.user_id) from memberships m where m.workspace_id = coalesce(new.id, old.id);
        return null;
    else
        affected := coalesce(new.user_id, old.user_id);
    end if;
    perform app_bump_scope(affected);
    return null;
end
$$;

drop trigger if exists scope_grants on matter_grants;
create trigger scope_grants after insert or update or delete on matter_grants
    for each row execute function app_scope_trigger();
drop trigger if exists scope_walls on matter_walls;
create trigger scope_walls after insert or update or delete on matter_walls
    for each row execute function app_scope_trigger();
drop trigger if exists scope_exceptions on access_exceptions;
create trigger scope_exceptions after insert or update or delete on access_exceptions
    for each row execute function app_scope_trigger();
drop trigger if exists scope_break_glass on break_glass_sessions;
create trigger scope_break_glass after insert or update or delete on break_glass_sessions
    for each row execute function app_scope_trigger();
drop trigger if exists scope_workspace_flags on workspaces;
create trigger scope_workspace_flags after update of admin_can_read_private, emergency_access, status on workspaces
    for each row execute function app_scope_trigger();

-- Revocation (8.6): any change to a membership's role, status or workspace bumps principal_version and notifies the
-- revocation consumer (gateway), which drops cached principals and cuts open streams.
create or replace function app_principal_trigger() returns trigger
    language plpgsql security definer set search_path = public, pg_temp
as $$
begin
    if (new.status, new.role, new.workspace_id) is distinct from (old.status, old.role, old.workspace_id) then
        new.principal_version := old.principal_version + 1;
        perform pg_notify('lmqa_revocation', new.user_id::text || ':' || new.principal_version);
    end if;
    return new;
end
$$;
drop trigger if exists principal_version_bump on memberships;
create trigger principal_version_bump before update on memberships
    for each row execute function app_principal_trigger();

-- Legal hold blocks deletion of documents (DEF-48), workspaces and organizations (9.5).
create or replace function app_block_held_delete() returns trigger
    language plpgsql security definer set search_path = public, pg_temp
as $$
begin
    if old.legal_hold
       or exists (select 1 from workspaces w where w.id = old.workspace_id and w.legal_hold)
       or exists (select 1 from organizations o where o.id = old.org_id and o.legal_hold) then
        raise exception 'legal hold: % % cannot be deleted', tg_table_name, old.id using errcode = 'P0001';
    end if;
    return old;
end
$$;
drop trigger if exists documents_legal_hold on documents;
create trigger documents_legal_hold before delete on documents
    for each row execute function app_block_held_delete();

-- The principal view (16.2): the only relation the gateway reads. No grants, walls or content.
create or replace view principal_v with (security_barrier = true) as
    select m.user_id, u.auth0_sub, m.org_id, m.workspace_id, m.role, m.status as membership_status,
           w.status as workspace_status, o.status as org_status, o.auth0_org_id,
           m.principal_version, m.scope_version, m.scope_hash, m.owner_linked, m.co_owner
    from memberships m
    join users u on u.id = m.user_id
    join organizations o on o.id = m.org_id
    left join workspaces w on w.id = m.workspace_id
    where m.status in ('pending_approval', 'active', 'suspended');  -- live memberships (Q-23)

-- Outbox (10.6): a change to what decides visibility is queued for the vector index in the same transaction, and
-- the version is marked stale; stale content stays searchable only where PostgreSQL still allows it (6.5).
create or replace function app_outbox_trigger() returns trigger
    language plpgsql security definer set search_path = public, pg_temp
as $$
begin
    if (new.visibility, new.matter_id, new.tier, new.owner_id)
       is distinct from (old.visibility, old.matter_id, old.tier, old.owner_id) then
        insert into index_outbox (org_id, workspace_id, document_id, version, operation)
        values (new.org_id, new.workspace_id, new.id, new.current_version, 'upsert_payload');
        update document_versions set index_state = 'stale' where document_id = new.id;
        update chunks set visibility = new.visibility, matter_id = new.matter_id, tier = new.tier,
                          owner_id = new.owner_id
         where document_id = new.id;
    end if;
    return new;
end
$$;
drop trigger if exists documents_outbox on documents;
create trigger documents_outbox after update of visibility, matter_id, tier, owner_id on documents
    for each row execute function app_outbox_trigger();

-- The caller's vector scope (10.5): the same facts app_can_read() uses, as one JSON value for the filter builder in
-- lmqa_vectorstore.qdrant. Keyed on app_user_id(); NULL when rule 1 denies.
create or replace function app_vector_scope() returns jsonb
    language sql stable security definer set search_path = public, pg_temp
as $$
    select case when app_active_workspace() is null then null else jsonb_build_object(
        'workspace_id', app_active_workspace(),
        'org_id', (select w.org_id from workspaces w where w.id = app_active_workspace()),
        'user_id', app_user_id(),
        'role', app_active_role(),
        'walled', coalesce((select jsonb_agg(w.matter_id) from matter_walls w where w.user_id = app_user_id()
                            and w.lifted_at is null and w.effective_from <= now()), '[]'::jsonb),
        'grants', coalesce((select jsonb_agg(jsonb_build_array(g.matter_id, g.max_tier)) from matter_grants g
                            where g.user_id = app_user_id() and g.workspace_id = app_active_workspace()
                              and (g.expires_at is null or g.expires_at > now())), '[]'::jsonb),
        'emergency', coalesce((select jsonb_agg(jsonb_build_array(e.matter_id, e.tier_cap)) from access_exceptions e
                               join workspaces w on w.id = e.workspace_id join organizations o on o.id = w.org_id
                               where e.user_id = app_user_id() and e.state = 'active' and e.expires_at > now()
                                 and w.emergency_access and o.kind in ('medical', 'both')), '[]'::jsonb),
        'break_glass', app_break_glass_active()
    ) end
$$;
