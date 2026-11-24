-- Identity production tables (blueprint 7, 8.6 to 8.8, 13.6): provisioning saga, notification outbox, review tasks,
-- alerts, step-up records. Additive.

create table provisioning_sagas (
    id              uuid primary key default uuidv7(),
    kind            text not null check (kind in ('organization', 'workspace', 'co_owner')),
    idempotency_key text not null,
    user_id         uuid not null references users (id),
    state           text not null default 'running' check (state in ('running', 'completed', 'compensating',
                                                                    'compensated', 'failed')),
    step            text not null default 'start',
    org_id          uuid,
    workspace_id    uuid,
    auth0_org_id    text,
    kms_key_ref     text,
    kms_replica_ref text,
    input           jsonb not null default '{}'::jsonb,
    error           text,
    attempts        int not null default 0,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (kind, user_id, idempotency_key)
);
create index provisioning_sagas_running on provisioning_sagas (updated_at) where state in ('running', 'compensating');

create table notifications (
    id          uuid primary key default uuidv7(),
    org_id      uuid,
    to_user_id  uuid references users (id),
    to_email_ciphertext bytea,
    kind        text not null,
    template_vars jsonb not null default '{}'::jsonb,
    state       text not null default 'pending' check (state in ('pending', 'sent', 'failed', 'dead')),
    attempts    int not null default 0,
    last_error  text,
    created_at  timestamptz not null default now(),
    sent_at     timestamptz
);
create index notifications_pending on notifications (created_at) where state = 'pending';

create table review_tasks (
    id           uuid primary key default uuidv7(),
    org_id       uuid not null,
    workspace_id uuid not null,
    kind         text not null check (kind in ('emergency_access', 'break_glass', 'ocr_review', 'citation_failure')),
    subject_id   uuid not null,
    assignee_id  uuid references users (id),
    state        text not null default 'open' check (state in ('open', 'closed')),
    due_at       timestamptz not null,
    alerted_48h  boolean not null default false,
    alerted_72h  boolean not null default false,
    outcome      text,
    closed_by    uuid references users (id),
    closed_at    timestamptz,
    created_at   timestamptz not null default now(),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade
);
create index review_tasks_open on review_tasks (workspace_id, due_at) where state = 'open';

create table alerts (
    id          bigint generated always as identity primary key,
    org_id      uuid,
    workspace_id uuid,
    rule        text not null,
    severity    text not null check (severity in ('info', 'warning', 'page')),
    summary     text not null,
    dedup_key   text not null,
    state       text not null default 'open' check (state in ('open', 'delivered', 'acknowledged', 'resolved')),
    delivered_at timestamptz,
    created_at  timestamptz not null default now()
);
create unique index alerts_dedup_open on alerts (dedup_key) where state in ('open', 'delivered');

create table step_up_events (
    id            uuid primary key default uuidv7(),
    user_id       uuid not null references users (id),
    authenticator_id text not null,
    strength      text not null check (strength in ('mfa', 'passkey', 'passkey_mfa')),
    auth_time     timestamptz not null,
    purpose       text not null,
    created_at    timestamptz not null default now()
);
create index step_up_events_user on step_up_events (user_id, created_at desc);

create table auth0_role_snapshots (
    org_id       uuid not null references organizations (id),
    auth0_user   text not null,
    roles        text[] not null,
    observed_at  timestamptz not null default now(),
    primary key (org_id, auth0_user)
);
