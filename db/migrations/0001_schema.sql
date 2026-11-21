-- 0001 schema (blueprint 16, MVP subset). Applied once by lmqa_owner; see libs/lmqa_db/migrate.py.
-- Functions, RLS policies and grants live in db/policies and db/roles and are re-applied on every migrate.

-- ---------------------------------------------------------------- identity and tenancy
create table users (
    id           uuid primary key default gen_random_uuid(),
    auth0_sub    text not null unique,
    email        text,
    name         text,
    created_at   timestamptz not null default now(),
    last_seen_at timestamptz
);

create table organizations (
    id         uuid primary key default gen_random_uuid(),
    name       text not null check (length(name) between 2 and 120),
    kind       text not null check (kind in ('legal', 'medical', 'both')),
    status     text not null default 'active' check (status in ('active', 'suspended')),
    created_by uuid references users (id),
    created_at timestamptz not null default now()
);

create table workspaces (
    id         uuid primary key default gen_random_uuid(),
    org_id     uuid not null references organizations (id) on delete cascade,
    name       text not null check (length(name) between 2 and 120),
    status     text not null default 'pending' check (status in ('pending', 'active', 'frozen', 'rejected')),
    created_at timestamptz not null default now(),
    unique (org_id, id)
);

create table memberships (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users (id) on delete cascade,
    org_id       uuid not null references organizations (id) on delete cascade,
    workspace_id uuid,
    role         text not null check (role in ('super_admin', 'admin', 'tenant')),
    status       text not null check (status in ('pending', 'active', 'rejected', 'suspended')),
    created_at   timestamptz not null default now(),
    decided_at   timestamptz,
    decided_by   uuid references users (id),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    check ((role = 'super_admin') = (workspace_id is null))
);
-- One live membership per user in v1 (blueprint A2); a rejected or withdrawn request may be retried.
create unique index memberships_one_live_per_user on memberships (user_id) where status <> 'rejected';
create unique index memberships_one_admin_per_workspace on memberships (workspace_id)
    where role = 'admin' and status <> 'rejected';
create index memberships_org_role on memberships (org_id, role, status);
create index memberships_workspace on memberships (workspace_id, status);

-- Organization Codes and Admin Codes (blueprint 7.6): only a keyed HMAC is stored.
create table join_codes (
    id           uuid primary key default gen_random_uuid(),
    kind         text not null check (kind in ('org', 'admin')),
    lookup_id    text not null unique,
    code_hmac    bytea not null,
    pepper_id    text not null,
    org_id       uuid not null references organizations (id) on delete cascade,
    workspace_id uuid,
    created_by   uuid not null references users (id),
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null,
    max_uses     int not null check (max_uses > 0),
    uses         int not null default 0 check (uses >= 0),
    revoked_at   timestamptz,
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    check ((kind = 'org') = (workspace_id is null))
);

-- ---------------------------------------------------------------- content (row-level security)
create table documents (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null,
    workspace_id uuid not null,
    owner_id     uuid not null references users (id),
    title        text not null,
    filename     text not null,
    file_type    text not null check (file_type in ('pdf', 'docx', 'html', 'xml', 'txt')),
    size_bytes   bigint not null,
    sha256       text not null,
    object_key   text not null,
    visibility   text not null check (visibility in ('workspace', 'private')),
    status       text not null default 'processing' check (status in ('processing', 'ready', 'failed')),
    error        text,
    notes        text,
    page_count   int,
    chunk_count  int,
    structure    text check (structure in ('detected', 'fallback')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    unique (org_id, workspace_id, id)
);
create index documents_workspace on documents (workspace_id, created_at desc);

create table chunks (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null,
    workspace_id uuid not null,
    document_id  uuid not null,
    owner_id     uuid not null,
    visibility   text not null check (visibility in ('workspace', 'private')),
    ordinal      int not null,
    kind         text not null check (kind in ('preamble', 'section', 'paragraph')),
    section      text,
    page_start   int,
    page_end     int,
    text         text not null check (length(text) > 0),
    text_sha256  text not null,
    token_count  int not null,
    embedding    vector(768),
    tsv          tsvector generated always as (to_tsvector('english', coalesce(section, '') || ' ' || text)) stored,
    -- Composite key: a chunk cannot point into another workspace's document (blueprint 5.1, G1.6).
    foreign key (org_id, workspace_id, document_id) references documents (org_id, workspace_id, id) on delete cascade,
    unique (document_id, ordinal)
);
create index chunks_embedding on chunks using hnsw (embedding vector_cosine_ops);
create index chunks_tsv on chunks using gin (tsv);
create index chunks_workspace on chunks (workspace_id);

create table queries (
    id            uuid primary key default gen_random_uuid(),
    org_id        uuid not null,
    workspace_id  uuid not null,
    user_id       uuid not null references users (id),
    question      text not null,
    outcome       text not null check (outcome in ('answered', 'partial', 'refused')),
    result        jsonb not null,
    model         text,
    prompt_sha256 text,
    tokens_in     int,
    tokens_out    int,
    latency_ms    int,
    created_at    timestamptz not null default now(),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade
);
create index queries_user on queries (user_id, created_at desc);

-- Retrieval ledger (blueprint 9.4): exactly what the model was shown, with content hashes.
create table retrieval_records (
    query_id     uuid not null references queries (id) on delete cascade,
    alias        text not null,
    chunk_id     uuid not null,
    chunk_sha256 text not null,
    rank         int not null,
    score        double precision not null,
    primary key (query_id, alias)
);

alter table documents enable row level security;
alter table documents force row level security;
alter table chunks enable row level security;
alter table chunks force row level security;
alter table queries enable row level security;
alter table queries force row level security;
alter table retrieval_records enable row level security;
alter table retrieval_records force row level security;

-- ---------------------------------------------------------------- audit (append-only, hash-chained)
create table audit_events (
    id           bigint generated always as identity primary key,
    org_id       uuid not null,
    workspace_id uuid,
    actor_id     uuid,
    action       text not null,
    target_type  text,
    target_id    text,
    payload      jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null,
    prev_hash    text not null,
    hash         text not null unique
);
create index audit_events_org on audit_events (org_id, id);
create index audit_events_workspace on audit_events (workspace_id, id);
