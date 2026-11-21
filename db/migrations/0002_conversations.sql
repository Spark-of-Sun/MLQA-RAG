-- 0002 conversations: multi-turn chats. A chat belongs to exactly one user in one workspace and is visible only
-- to that user (row-level security in db/policies/20_rls.sql). Admins cannot read members' chats.

create table conversations (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null,
    workspace_id uuid not null,
    user_id      uuid not null references users (id) on delete cascade,
    title        text not null check (length(title) between 1 and 200),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    unique (id, user_id, workspace_id)
);
create index conversations_user on conversations (user_id, workspace_id, updated_at desc);

alter table conversations enable row level security;
alter table conversations force row level security;

alter table queries add column conversation_id uuid;
alter table queries add column standalone_question text;

-- Backfill: earlier questions (asked before chats existed) are grouped into chats by session, per user and
-- workspace: a gap of more than 30 minutes starts a new chat, so one chat holds many questions, as in any chat app.
-- FORCE RLS also binds the owner, so lift it for the length of this transaction only.
alter table queries no force row level security;
alter table conversations no force row level security;

create temporary table _query_sessions on commit drop as
with ordered as (
    select q.id, q.org_id, q.workspace_id, q.user_id, q.question, q.created_at,
           case when lag(q.created_at) over w is null
                  or q.created_at - lag(q.created_at) over w > interval '30 minutes' then 1 else 0 end as starts
    from queries q
    where q.conversation_id is null
    window w as (partition by q.user_id, q.workspace_id order by q.created_at, q.id)
)
select o.*, sum(o.starts) over (partition by o.user_id, o.workspace_id order by o.created_at, o.id) as session_no
from ordered o;

create temporary table _query_chats on commit drop as
select distinct on (s.user_id, s.workspace_id, s.session_no)
       s.id as chat_id, s.org_id, s.workspace_id, s.user_id, s.session_no, s.question as first_question,
       s.created_at as started_at
from _query_sessions s
order by s.user_id, s.workspace_id, s.session_no, s.created_at, s.id;

insert into conversations (id, org_id, workspace_id, user_id, title, created_at, updated_at)
select c.chat_id, c.org_id, c.workspace_id, c.user_id, left(c.first_question, 80), c.started_at,
       (select max(s.created_at) from _query_sessions s
        where s.user_id = c.user_id and s.workspace_id = c.workspace_id and s.session_no = c.session_no)
from _query_chats c;

update queries q set conversation_id = c.chat_id
from _query_sessions s
join _query_chats c on c.user_id = s.user_id and c.workspace_id = s.workspace_id and c.session_no = s.session_no
where q.id = s.id;

alter table queries force row level security;
alter table conversations force row level security;

alter table queries alter column conversation_id set not null;
-- Composite key: a question can only be attached to a chat of the same user in the same workspace.
alter table queries add constraint queries_conversation_fk
    foreign key (conversation_id, user_id, workspace_id)
    references conversations (id, user_id, workspace_id) on delete cascade;
create index queries_conversation on queries (conversation_id, created_at);
