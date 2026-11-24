-- Access decision rules 1 to 8 only (blueprint 5.4, KD-3, R-4.1; closes DEV-14, DEV-15). Pending Q-05 and Q-37.
--
-- The MVP rules 7a (visibility 'workspace') and 7b (document_shares) leave the access decision. app_can_read() in
-- db/policies/11_access.sql no longer reads either; this revision moves the data.
--
-- Q-37 is open, so existing documents follow the v3.1 default that adds no access: a 'workspace' document reverts
-- to 'private' (only its owner reads it, rule 3), and document_shares rows stay in place but decide nothing. Both
-- facts are kept, so an answer of "convert to matters with grants" can still be carried out later:
--   mvp_visibility_archive  one row per document that was 'workspace' (its previous visibility)
--   document_shares         unchanged; still referenced by the frozen named_shares feature (task 3.6)
-- Nothing at runtime reads mvp_visibility_archive: FORCE RLS and no policy for any runtime role.

create table mvp_visibility_archive (
    document_id         uuid primary key,
    org_id              uuid not null,
    workspace_id        uuid not null,
    previous_visibility text not null check (previous_visibility = 'workspace'),
    archived_at         timestamptz not null default now(),
    foreign key (org_id, workspace_id, document_id) references documents (org_id, workspace_id, id) on delete cascade
);

-- The migration owner rewrites rows under FORCE RLS only with RLS relaxed for this transaction; 15_force_rls.sql
-- forces it again on every migrate, and the statements at the end of this file do so already.
alter table documents no force row level security;
alter table chunks no force row level security;
alter table documents disable row level security;
alter table chunks disable row level security;

insert into mvp_visibility_archive (document_id, org_id, workspace_id, previous_visibility)
select id, org_id, workspace_id, visibility from documents where visibility = 'workspace';

-- The documents_outbox trigger also syncs chunk columns and queues a payload update for the vector index.
update documents set visibility = 'private' where visibility = 'workspace';
update chunks set visibility = 'private' where visibility = 'workspace';

alter table documents drop constraint if exists documents_visibility_check;
alter table documents add constraint documents_visibility_check check (visibility in ('private', 'matter'));
alter table chunks drop constraint if exists chunks_visibility_check;
alter table chunks add constraint chunks_visibility_check check (visibility in ('private', 'matter'));

alter table documents enable row level security;
alter table chunks enable row level security;
alter table documents force row level security;
alter table chunks force row level security;
alter table mvp_visibility_archive enable row level security;
alter table mvp_visibility_archive force row level security;
