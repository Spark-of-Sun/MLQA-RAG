-- Production data model, part 1 (blueprint 16.2, 5.4 to 5.8, 6, 12, 13). Additive: every MVP column and table keeps
-- working, so the MVP flows run unchanged while the production paths are switched on feature by feature
-- (contracts/features.toml). New primary keys are UUIDv7 (PostgreSQL 18 `uuidv7()`), as section 16.1 requires.

-- ---------------------------------------------------------------------------------------------------------------
-- Organizations, workspaces, users, memberships: production states and policy fields
-- ---------------------------------------------------------------------------------------------------------------
alter table organizations drop constraint if exists organizations_status_check;
alter table organizations add constraint organizations_status_check check (status in (
    'pending', 'active', 'suspended', 'rejected', 'frozen', 'deletion_pending', 'sealed', 'destroyed'));
alter table organizations
    add column auth0_org_id      text unique,
    add column region            text not null default 'us-east-1',
    add column deployment        text not null default 'pooled' check (deployment in ('pooled', 'silo')),
    add column retention_days    int not null default 2190 check (retention_days > 0),
    add column legal_hold        boolean not null default false,
    add column kms_key_ref       text,
    add column deletion_requested_at timestamptz,
    add column state_changed_at  timestamptz not null default now();

alter table workspaces drop constraint if exists workspaces_status_check;
alter table workspaces add constraint workspaces_status_check check (status in (
    'pending', 'provisioning', 'active', 'frozen', 'sealed', 'destroyed', 'rejected'));
alter table workspaces
    add column admin_user_id          uuid references users (id),
    add column admin_can_read_private boolean not null default false,
    add column emergency_access       boolean not null default false,
    add column join_policy            text not null default 'manual'
        check (join_policy in ('manual', 'domain_allowlist', 'auto')),
    add column allowed_domains        text[] not null default '{}',
    add column delivery_mode          text not null default 'sentence' check (delivery_mode in ('sentence', 'buffered')),
    add column on_fail                text not null default 'strip' check (on_fail in ('strip', 'regenerate')),
    add column legal_hold             boolean not null default false,
    add column frozen_at              timestamptz,
    add column sealed_at              timestamptz,
    add column state_changed_at       timestamptz not null default now();

alter table users
    add column email_blind_index  bytea,
    add column email_ciphertext   bytea,
    add column auth_strength_last text check (auth_strength_last in ('otp', 'mfa', 'passkey', 'passkey_mfa')),
    add column auth_methods_last  text[];
create unique index if not exists users_email_blind_index on users (email_blind_index) where email_blind_index is not null;

alter table memberships drop constraint if exists memberships_status_check;
alter table memberships add constraint memberships_status_check check (status in (
    'pending', 'pending_approval', 'active', 'rejected', 'suspended', 'removed'));
alter table memberships
    add column state_reason      text check (state_reason in (
        'requested', 'approved', 'rejected', 'suspended_by_admin', 'suspended_by_super_admin', 'workspace_frozen',
        'org_frozen', 'removed', 'successor_effective', 'reactivated')),
    add column principal_version bigint not null default 1,
    add column scope_version     bigint not null default 1,
    add column scope_hash        text not null default '',
    add column owner_linked      boolean not null default false,
    add column co_owner          boolean not null default false,
    add constraint memberships_no_self_approval check (decided_by is null or decided_by <> user_id);

-- ---------------------------------------------------------------------------------------------------------------
-- Matters, grants, walls, emergency exceptions, break-glass sessions (5.4 to 5.8)
-- ---------------------------------------------------------------------------------------------------------------
create table matters (
    id           uuid primary key default uuidv7(),
    org_id       uuid not null,
    workspace_id uuid not null,
    label        text not null check (length(label) between 1 and 200),
    kind         text not null check (kind in ('matter', 'patient')),
    created_by   uuid not null references users (id),
    created_at   timestamptz not null default now(),
    closed_at    timestamptz,
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    unique (org_id, workspace_id, id)
);

create table matter_grants (
    id           uuid primary key default uuidv7(),
    org_id       uuid not null,
    workspace_id uuid not null,
    matter_id    uuid not null,
    user_id      uuid not null references users (id),
    max_tier     smallint not null check (max_tier between 1 and 4),
    granted_by   uuid not null references users (id),
    granted_at   timestamptz not null default now(),
    expires_at   timestamptz,
    foreign key (org_id, workspace_id, matter_id) references matters (org_id, workspace_id, id) on delete cascade,
    unique (matter_id, user_id),
    check (granted_by <> user_id)
);
create index matter_grants_user on matter_grants (user_id, workspace_id);

create table matter_walls (
    id             uuid primary key default uuidv7(),
    org_id         uuid not null,
    workspace_id   uuid not null,
    matter_id      uuid not null,
    user_id        uuid not null references users (id),
    reason_code    text not null check (reason_code in (
        'conflict_of_interest', 'lateral_hire', 'client_instruction', 'personal_relationship', 'other')),
    created_by     uuid not null references users (id),
    effective_from timestamptz not null default now(),
    lifted_at      timestamptz,
    lifted_by_request uuid,
    foreign key (org_id, workspace_id, matter_id) references matters (org_id, workspace_id, id) on delete cascade
);
create unique index matter_walls_live on matter_walls (matter_id, user_id) where lifted_at is null;
create index matter_walls_user on matter_walls (user_id) where lifted_at is null;

create table access_exceptions (
    id            uuid primary key default uuidv7(),
    org_id        uuid not null,
    workspace_id  uuid not null,
    matter_id     uuid not null,
    user_id       uuid not null references users (id),
    kind          text not null default 'emergency' check (kind = 'emergency'),
    reason_code   text not null check (reason_code in ('treatment_emergency', 'urgent_care_continuity', 'other')),
    note          text check (length(note) <= 2000),
    state         text not null default 'active' check (state in (
        'requested', 'approved', 'denied', 'active', 'expired', 'revoked', 'reviewed')),
    tier_cap      smallint not null default 3 check (tier_cap between 1 and 3),
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null,
    revoked_at    timestamptz,
    review_state  text not null default 'open' check (review_state in ('open', 'closed')),
    review_due_at timestamptz not null,
    reviewed_by   uuid references users (id),
    reviewed_at   timestamptz,
    foreign key (org_id, workspace_id, matter_id) references matters (org_id, workspace_id, id) on delete cascade,
    check (expires_at <= created_at + interval '60 minutes')
);
create index access_exceptions_user on access_exceptions (user_id, created_at desc);

create table break_glass_sessions (
    id            uuid primary key default uuidv7(),
    org_id        uuid not null,
    workspace_id  uuid not null,
    admin_user_id uuid not null references users (id),
    reason        text not null check (length(reason) between 10 and 2000),
    state         text not null default 'active' check (state in (
        'requested', 'approved', 'denied', 'active', 'expired', 'revoked', 'reviewed')),
    step_up_at    timestamptz not null,
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null,
    revoked_at    timestamptz,
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade,
    check (expires_at <= created_at + interval '60 minutes')
);
create index break_glass_admin on break_glass_sessions (admin_user_id, expires_at desc);

-- ---------------------------------------------------------------------------------------------------------------
-- Documents, versions, chunks: matters, tiers, retention, holds, lifecycle, encryption (11.2, 12)
-- ---------------------------------------------------------------------------------------------------------------
alter table documents drop constraint if exists documents_visibility_check;
alter table documents add constraint documents_visibility_check check (visibility in ('workspace', 'private', 'matter'));
alter table documents
    add column matter_id        uuid,
    add column tier             smallint not null default 1 check (tier between 1 and 4),
    add column lifecycle        text not null default 'indexed' check (lifecycle in (
        'uploading', 'scanning', 'parsing', 'ocr_review', 'indexing', 'indexed', 'failed', 'held', 'deleting',
        'deleted')),
    add column current_version  int not null default 1,
    add column retention_until  timestamptz,
    add column legal_hold       boolean not null default false,
    add column content_sha256   text,
    add constraint documents_matter_visibility check ((visibility = 'matter') = (matter_id is not null)),
    add constraint documents_matter_fk foreign key (org_id, workspace_id, matter_id)
        references matters (org_id, workspace_id, id);
create index documents_matter on documents (matter_id) where matter_id is not null;

create table document_versions (
    org_id          uuid not null,
    workspace_id    uuid not null,
    document_id     uuid not null,
    version         int not null check (version > 0),
    text_source     text not null check (text_source in ('text_layer', 'ocr', 'mixed', 'structured')),
    index_state     text not null default 'in_sync' check (index_state in ('in_sync', 'stale', 'reindexing')),
    object_key      text not null,
    object_version  text,
    ciphertext_sha256 text,
    embedding_version text,
    ocr_min_confidence real,
    created_at      timestamptz not null default now(),
    primary key (document_id, version),
    foreign key (org_id, workspace_id, document_id) references documents (org_id, workspace_id, id) on delete cascade
);

alter table chunks drop constraint if exists chunks_visibility_check;
alter table chunks add constraint chunks_visibility_check check (visibility in ('workspace', 'private', 'matter'));
alter table chunks
    add column matter_id       uuid,
    add column tier            smallint not null default 1 check (tier between 1 and 4),
    add column version         int not null default 1,
    add column char_start      int,
    add column char_end        int,
    add column heading_path    text[],
    add column clause_label    text,
    add column ocr_confidence  real,
    add column text_ciphertext bytea,
    add column key_version     int,
    add column embedding_version text;
create index chunks_matter on chunks (matter_id) where matter_id is not null;

-- ---------------------------------------------------------------------------------------------------------------
-- Key hierarchy (12.2): CMK per organization in KMS; wrapped workspace, document and audit keys here
-- ---------------------------------------------------------------------------------------------------------------
create table org_keys (
    org_id              uuid not null references organizations (id),
    key_version         int not null,
    provider            text not null check (provider in ('aws_kms', 'openbao')),
    key_ref             text not null,
    replica_ref         text,
    escrow_ref          text,
    state               text not null default 'enabled' check (state in (
        'enabled', 'disabled', 'pending_deletion', 'destroyed')),
    deletion_protection boolean not null default true,
    created_at          timestamptz not null default now(),
    primary key (org_id, key_version)
);

create table workspace_keys (
    org_id       uuid not null,
    workspace_id uuid not null,
    key_version  int not null,
    wrapped_key  bytea not null,
    wrapped_by   int not null,
    escrow_wrapped bytea,          -- copy under the organization's escrow CMK (vault account, two custodians)
    state        text not null default 'active' check (state in ('active', 'retired', 'destroyed')),
    created_at   timestamptz not null default now(),
    primary key (workspace_id, key_version),
    foreign key (org_id, workspace_id) references workspaces (org_id, id),
    foreign key (org_id, wrapped_by) references org_keys (org_id, key_version)
);

create table doc_keys (
    org_id       uuid not null,
    workspace_id uuid not null,
    document_id  uuid not null,
    key_version  int not null,
    wrapped_key  bytea not null,
    wrapped_by   int not null,
    state        text not null default 'active' check (state in ('active', 'destroyed')),
    created_at   timestamptz not null default now(),
    destroyed_at timestamptz,
    primary key (document_id, key_version),
    foreign key (workspace_id, wrapped_by) references workspace_keys (workspace_id, key_version)
);

create table audit_keys (
    org_id      uuid not null references organizations (id),
    month       date not null check (extract(day from month) = 1),
    public_key  bytea not null,
    wrapped_private_key bytea,
    state       text not null default 'active' check (state in ('active', 'retired', 'destroyed')),
    created_at  timestamptz not null default now(),
    primary key (org_id, month)
);

-- ---------------------------------------------------------------------------------------------------------------
-- Outbox, tombstones, idempotency, quotas, usage (10.6, 12.6, 13.5, 15)
-- ---------------------------------------------------------------------------------------------------------------
create table index_outbox (
    id           bigint generated always as identity primary key,
    org_id       uuid not null,
    workspace_id uuid not null,
    document_id  uuid not null,
    version      int not null,
    operation    text not null check (operation in ('upsert_payload', 'delete_vectors', 'reindex')),
    attempts     int not null default 0,
    state        text not null default 'pending' check (state in ('pending', 'done', 'dead')),
    last_error   text,
    created_at   timestamptz not null default now(),
    done_at      timestamptz
);
create index index_outbox_pending on index_outbox (created_at) where state = 'pending';

create table deletion_tombstones (
    id           uuid primary key default uuidv7(),
    org_id       uuid not null,
    workspace_id uuid,
    scope        text not null check (scope in ('document', 'workspace', 'organization', 'audit_month')),
    target_id    text not null,
    key_refs     text[] not null default '{}',
    approver_refs uuid[] not null default '{}',
    created_at   timestamptz not null default now(),
    mirrored_at  timestamptz
);
create index deletion_tombstones_unmirrored on deletion_tombstones (created_at) where mirrored_at is null;

create table idempotency_keys (
    key          text not null,
    user_id      uuid not null,
    method       text not null,
    path         text not null,
    request_sha256 text not null,
    status_code  int,
    response     jsonb,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null default now() + interval '24 hours',
    primary key (user_id, key)
);

create table quotas (
    scope        text not null check (scope in ('organization', 'workspace', 'tenant')),
    scope_id     uuid not null,
    org_id       uuid not null,
    queries_per_minute  int,
    queries_per_day     int,
    uploads_per_day     int,
    storage_bytes       bigint,
    llm_tokens_per_day  bigint,
    spend_cap_usd_month numeric(12, 2),
    updated_at   timestamptz not null default now(),
    primary key (scope, scope_id)
);

create table workspace_usage (
    workspace_id uuid primary key,
    org_id       uuid not null,
    tenants      int not null default 0,
    documents    int not null default 0,
    queries      bigint not null default 0,
    tokens_in    bigint not null default 0,
    tokens_out   bigint not null default 0,
    refreshed_at timestamptz not null default now(),
    foreign key (org_id, workspace_id) references workspaces (org_id, id) on delete cascade
);

-- ---------------------------------------------------------------------------------------------------------------
-- Onboarding attempts and governance (7.6, 6.7)
-- ---------------------------------------------------------------------------------------------------------------
alter table join_codes drop constraint if exists join_codes_kind_check;
alter table join_codes add constraint join_codes_kind_check check (kind in ('org', 'admin', 'successor'));
alter table join_codes drop constraint if exists join_codes_check;
alter table join_codes add constraint join_codes_scope check ((kind = 'org') = (workspace_id is null));
alter table join_codes
    add column state       text not null default 'active' check (state in (
        'active', 'rotated', 'expired', 'exhausted', 'disabled', 'revoked')),
    add column bound_email_blind_index bytea;

create table join_attempts (
    id          bigint generated always as identity primary key,
    lookup_id   text,
    user_id     uuid,
    ip_hash     bytea,
    outcome     text not null check (outcome in ('ok', 'rejected')),
    true_reason text not null,
    created_at  timestamptz not null default now()
);
create index join_attempts_user on join_attempts (user_id, created_at desc);
create index join_attempts_ip on join_attempts (ip_hash, created_at desc);

create table governance_requests (
    id            uuid primary key default uuidv7(),
    org_id        uuid not null references organizations (id),
    workspace_id  uuid,
    kind          text not null check (kind in (
        'successor_transfer', 'private_read_enable', 'wall_lift', 'workspace_unseal', 'workspace_destroy',
        'org_delete', 'owner_recovery', 'co_owner_set')),
    target_type   text not null,
    target_id     uuid not null,
    reason_code   text not null,
    initiator_id  uuid not null,
    initiator_kind text not null default 'user' check (initiator_kind in ('user', 'operator')),
    state         text not null default 'requested' check (state in (
        'requested', 'approved', 'waiting', 'executable', 'executed', 'rejected', 'cancelled', 'expired', 'failed')),
    approvals_required int not null default 1 check (approvals_required between 1 and 3),
    wait_seconds  int not null check (wait_seconds >= 0),
    wait_until    timestamptz,
    expires_at    timestamptz not null,
    executed_at   timestamptz,
    failure       text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);
create index governance_requests_org on governance_requests (org_id, state, created_at desc);
create unique index governance_one_open_per_target on governance_requests (kind, target_id)
    where state in ('requested', 'approved', 'waiting', 'executable');

create table governance_approvals (
    request_id    uuid not null references governance_requests (id) on delete cascade,
    approver_id   uuid not null,
    approver_kind text not null default 'user' check (approver_kind in ('user', 'operator')),
    authenticator_id text not null,
    step_up_at    timestamptz not null,
    decision      text not null check (decision in ('approve', 'reject', 'veto')),
    created_at    timestamptz not null default now(),
    primary key (request_id, approver_id),
    unique (request_id, authenticator_id)
);

-- ---------------------------------------------------------------------------------------------------------------
-- Audit: sealed payloads, checkpoints and anchors (13.1 to 13.4)
-- ---------------------------------------------------------------------------------------------------------------
alter table audit_events
    add column severity        text not null default 'info' check (severity in ('info', 'notice', 'warning', 'break_glass', 'critical')),
    add column request_id      uuid,
    add column sealed_payload  bytea,
    add column payload_key_month date;

create table audit_checkpoints (
    org_id       uuid not null,
    last_event_id bigint not null,
    chain_hash   text not null,
    reason       text not null check (reason in ('hourly', 'partition_detach', 'manual')),
    created_at   timestamptz not null default now(),
    primary key (org_id, last_event_id)
);

create table audit_anchors (
    id           bigint generated always as identity primary key,
    period_start timestamptz not null,
    period_end   timestamptz not null,
    merkle_root  text not null,
    leaf_count   int not null,
    object_key   text not null,
    object_version text,
    created_at   timestamptz not null default now(),
    unique (period_start)
);

-- ---------------------------------------------------------------------------------------------------------------
-- Operator plane: separate schema (14)
-- ---------------------------------------------------------------------------------------------------------------
create schema if not exists ops;
revoke all on schema ops from public;

create table ops.operator_accounts (
    id          uuid primary key default uuidv7(),
    idp_subject text not null unique,
    display_name text not null,
    roles       text[] not null check (roles <@ array['sre', 'support', 'security_officer', 'key_custodian']::text[]),
    state       text not null default 'active' check (state in ('active', 'suspended', 'removed')),
    background_check_at date,
    training_at date,
    created_at  timestamptz not null default now()
);

create table ops.operator_access_grants (
    id           uuid primary key default uuidv7(),
    operator_id  uuid not null references ops.operator_accounts (id),
    org_id       uuid not null,
    workspace_id uuid,
    plane        text not null check (plane in ('infrastructure', 'control', 'content')),
    reason       text not null check (length(reason) between 10 and 2000),
    ticket_ref   text not null,
    state        text not null default 'requested' check (state in (
        'requested', 'approved', 'denied', 'active', 'expired', 'revoked', 'reviewed')),
    approved_by  uuid,
    customer_approved_by uuid,
    created_at   timestamptz not null default now(),
    starts_at    timestamptz,
    expires_at   timestamptz,
    revoked_at   timestamptz,
    check (approved_by is null or approved_by <> operator_id),
    check (plane <> 'content' or workspace_id is not null),
    check (expires_at is null or expires_at <= coalesce(starts_at, created_at) + case plane
        when 'infrastructure' then interval '24 hours' when 'control' then interval '8 hours'
        else interval '4 hours' end)
);
create index operator_grants_live on ops.operator_access_grants (operator_id, expires_at) where state = 'active';

create table ops.security_holds (
    id         uuid primary key default uuidv7(),
    org_id     uuid not null,
    reason     text not null,
    created_by uuid not null references ops.operator_accounts (id),
    created_at timestamptz not null default now(),
    released_at timestamptz
);
