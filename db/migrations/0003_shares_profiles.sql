-- 0003 per-person document shares and member profiles.
--
-- document_shares: an explicit grant of one document to one person in the same workspace. A member may share their
-- own document with their workspace admin; the admin may share their own document with chosen members. The rules
-- are enforced by row-level security and app_share_target_ok() in db/policies.
-- Owner and workspace are copied onto the share row, so its RLS policy never has to read `documents` (which reads
-- `document_shares`): no policy recursion.

create table document_shares (
    org_id       uuid not null,
    workspace_id uuid not null,
    document_id  uuid not null,
    owner_id     uuid not null references users (id) on delete cascade,
    user_id      uuid not null references users (id) on delete cascade,
    created_at   timestamptz not null default now(),
    primary key (document_id, user_id),
    -- Composite key: a share cannot point into another workspace's document (blueprint 5.1).
    foreign key (org_id, workspace_id, document_id) references documents (org_id, workspace_id, id) on delete cascade,
    check (owner_id <> user_id)
);
create index document_shares_user on document_shares (user_id, workspace_id);

alter table document_shares enable row level security;
alter table document_shares force row level security;

-- Profile details a member edits on the Profile page; their admin can read them. Email stays the Auth0 login.
-- Once a person edits their profile, sign-in no longer overwrites their name with the Auth0 name.
alter table users add column job_title text check (length(job_title) <= 120);
alter table users add column department text check (length(department) <= 120);
alter table users add column phone text check (length(phone) <= 40);
alter table users add column profile_updated_at timestamptz;

create index audit_events_actor on audit_events (actor_id, id);
