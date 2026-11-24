-- 0009 tenancy and membership schema (R-1 criteria 3, 4 and 7; R-78; Q-23; schema part of DEV-17).
-- Forward-only, applied once by lmqa_owner through Alembic (revision 0009_tenancy_membership).
--
-- 1. Membership states are exactly the five of section 6.2; MVP `pending` rows become `pending_approval`.
-- 2. "Live" means pending_approval, active or suspended (Q-23). The MVP indexes counted every state except
--    `rejected`, so a removed membership blocked re-onboarding and the 7.8 successor join; both are rebuilt here.
-- 3. The approver column is `approver_id` (was `decided_by`) and can never be the member (CHECK).
-- 4. A membership's role never changes (R-1 criterion 8): a trigger refuses it for every role, the table owner
--    included, and db/roles/grants.sql grants UPDATE only on the mutable columns.
-- 5. Every foreign key between two workspace tables carries org_id and workspace_id (R-1 criteria 3 and 4).
-- The workspace path pending -> provisioning -> active is enforced by the transition trigger generated from
-- contracts/state-machines.yaml (db/policies/40_transitions.sql); the status CHECK already allows `provisioning`.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. Membership states
-- ---------------------------------------------------------------------------------------------------------------
-- The transition trigger (re-applied by every migrate) would refuse pending -> pending_approval, which is a rename,
-- not a lifecycle step. It does not exist yet on a fresh database.
do $$
declare
    guarded boolean := exists (select 1 from pg_trigger
                               where tgrelid = 'memberships'::regclass and tgname = 'transition_status');
begin
    if guarded then
        alter table memberships disable trigger transition_status;
    end if;
    update memberships set status = 'pending_approval' where status = 'pending';
    if guarded then
        alter table memberships enable trigger transition_status;
    end if;
end
$$;

alter table memberships drop constraint memberships_status_check;
alter table memberships add constraint memberships_status_check
    check (status in ('pending_approval', 'active', 'rejected', 'suspended', 'removed'));

-- ---------------------------------------------------------------------------------------------------------------
-- 2. One live membership per user, one live admin per workspace (Q-23)
-- ---------------------------------------------------------------------------------------------------------------
drop index memberships_one_live_per_user;
drop index memberships_one_admin_per_workspace;
create unique index memberships_one_live_per_user on memberships (user_id)
    where status in ('pending_approval', 'active', 'suspended');
create unique index memberships_one_admin_per_workspace on memberships (workspace_id)
    where role = 'admin' and status in ('pending_approval', 'active', 'suspended');

-- ---------------------------------------------------------------------------------------------------------------
-- 3. Approver
-- ---------------------------------------------------------------------------------------------------------------
alter table memberships rename column decided_by to approver_id;
alter table memberships drop constraint memberships_no_self_approval;
alter table memberships add constraint memberships_no_self_approval check (approver_id <> user_id);

-- ---------------------------------------------------------------------------------------------------------------
-- 4. No role-update path
-- ---------------------------------------------------------------------------------------------------------------
create function app_membership_role_immutable() returns trigger
    language plpgsql set search_path = public, pg_temp
as $$
begin
    if new.role is distinct from old.role then
        raise exception 'membership role is immutable (% -> %): remove the membership and onboard again',
            old.role, new.role
            using errcode = '23514', constraint = 'memberships_role_immutable';
    end if;
    return new;
end
$$;
revoke all on function app_membership_role_immutable() from public;
create trigger memberships_role_immutable before update of role on memberships
    for each row execute function app_membership_role_immutable();

-- ---------------------------------------------------------------------------------------------------------------
-- 5. Composite foreign keys between workspace tables
-- ---------------------------------------------------------------------------------------------------------------
alter table workspace_keys add constraint workspace_keys_scope_key unique (org_id, workspace_id, key_version);
alter table doc_keys drop constraint doc_keys_workspace_id_wrapped_by_fkey;
alter table doc_keys add constraint doc_keys_wrapped_by_fkey foreign key (org_id, workspace_id, wrapped_by)
    references workspace_keys (org_id, workspace_id, key_version);

alter table conversations add constraint conversations_scope_key unique (org_id, workspace_id, user_id, id);
alter table queries drop constraint queries_conversation_fk;
alter table queries add constraint queries_conversation_fk
    foreign key (org_id, workspace_id, user_id, conversation_id)
    references conversations (org_id, workspace_id, user_id, id) on delete cascade;

alter table queries add constraint queries_scope_key unique (org_id, workspace_id, id);
alter table query_segments drop constraint query_segments_query_id_fkey;
alter table query_segments add constraint query_segments_query_fkey foreign key (org_id, workspace_id, query_id)
    references queries (org_id, workspace_id, id) on delete cascade;
