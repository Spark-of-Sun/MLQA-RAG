-- Audit chains (KD-10, DEV-18; R-60.2, R-60.4, R-61.1, R-61.4, R-61.5; design "Audit" tables).
--
-- The MVP kept one SHA-256 chain per organization in an unpartitioned audit_events table, with sealed payloads in a
-- column. From here on:
--   audit_chains       one chain per workspace and one control chain per organization (workspace_id null); the head
--                      (last seq and hash) is the row audit_append locks and advances
--   audit_events       partitioned by calendar month (UTC); metadata only (`meta`, R-60.5), the SHA-256 of the sealed
--                      payload (`payload_ct_sha256`, R-60.4) and the chain link (`chain_id`, `seq`, `prev_hash`, `hash`)
--   audit_payloads     partitioned the same way; the HPKE ciphertext and the workspace-month audit key it is sealed to
--   audit_checkpoints  a valid chain start: written before a partition is detached, hourly with each anchor, and once
--                      here to close the MVP chain
-- The functions (audit_append, audit_verify, partition maintenance, detach) are in db/policies/30_audit.sql and
-- 31_audit_sealed.sql, re-applied on every migrate.
--
-- Closing the MVP chain: existing rows cannot be rewritten (UPDATE and DELETE are trigger-blocked), so the old table
-- is kept as the read-only archive audit_events_mvp, verifiable with audit_verify_mvp(org). Each organization's new
-- control chain starts from the archive's last hash: a `legacy_close` checkpoint records it, so the new chain commits
-- to the whole MVP history. Workspace chains start from the zero hash.

-- ---------------------------------------------------------------------------------------------------------------
-- 1. Archive the MVP table and its functions
-- ---------------------------------------------------------------------------------------------------------------
drop function if exists audit_append(uuid, uuid, uuid, text, text, text, jsonb);
drop function if exists audit_append_sealed(uuid, uuid, uuid, text, text, text, bytea, date, text, uuid);
drop function if exists audit_verify(uuid);
drop function if exists audit_checkpoint(uuid, text);
drop function if exists audit_anchor_leaves(timestamptz);
drop function if exists audit_event_hash(audit_events);
drop function if exists audit_material(uuid, uuid, uuid, text, text, text, jsonb, timestamptz, text);
drop function if exists audit_material_sealed(uuid, uuid, uuid, text, text, text, bytea, date, text, uuid, timestamptz,
                                              text);

alter table audit_events rename to audit_events_mvp;
alter index audit_events_pkey rename to audit_events_mvp_pkey;
alter index audit_events_hash_key rename to audit_events_mvp_hash_key;
alter index audit_events_org rename to audit_events_mvp_org;
alter index audit_events_workspace rename to audit_events_mvp_workspace;
alter index if exists audit_events_actor rename to audit_events_mvp_actor;
alter sequence audit_events_id_seq rename to audit_events_mvp_id_seq;
drop policy if exists audit_reader on audit_events_mvp;

-- The MVP material formats, kept only to verify the archive.
create function audit_material_mvp(
    p_org uuid, p_ws uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
    p_payload jsonb, p_ts timestamptz, p_prev text
) returns text
    language sql stable
as $$
    select concat_ws('|', p_org::text, coalesce(p_ws::text, ''), coalesce(p_actor::text, ''), p_action,
                     coalesce(p_target_type, ''), coalesce(p_target_id, ''), p_payload::text,
                     to_char(p_ts at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), p_prev)
$$;

create function audit_event_hash_mvp(r audit_events_mvp) returns text
    language sql stable
as $$
    select encode(sha256(convert_to(case when r.sealed_payload is null then
        audit_material_mvp(r.org_id, r.workspace_id, r.actor_id, r.action, r.target_type, r.target_id, r.payload,
                           r.created_at, r.prev_hash)
    else
        concat_ws('|', 'v2', r.org_id::text, coalesce(r.workspace_id::text, ''), coalesce(r.actor_id::text, ''),
                  r.action, coalesce(r.target_type, ''), coalesce(r.target_id, ''),
                  encode(sha256(r.sealed_payload), 'hex'), r.payload_key_month::text, r.severity,
                  coalesce(r.request_id::text, ''),
                  to_char(r.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), r.prev_hash)
    end, 'UTF8')), 'hex')
$$;

create function audit_verify_mvp(p_org uuid) returns table (ok boolean, checked bigint, first_bad_id bigint)
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    r      audit_events_mvp;
    v_prev text := repeat('0', 64);
    n      bigint := 0;
begin
    for r in select * from audit_events_mvp where org_id = p_org order by id loop
        n := n + 1;
        if r.prev_hash <> v_prev or r.hash <> audit_event_hash_mvp(r) then
            return query select false, n, r.id;
            return;
        end if;
        v_prev := r.hash;
    end loop;
    return query select true, n, null::bigint;
end
$$;
revoke all on function audit_material_mvp(uuid, uuid, uuid, text, text, text, jsonb, timestamptz, text),
    audit_event_hash_mvp(audit_events_mvp), audit_verify_mvp(uuid) from public;

-- ---------------------------------------------------------------------------------------------------------------
-- 2. Chains, partitioned events and payloads, checkpoints
-- ---------------------------------------------------------------------------------------------------------------
create table audit_chains (
    id            uuid primary key default uuidv7(),
    org_id        uuid not null references organizations (id),
    workspace_id  uuid,
    head_seq      bigint not null default 0 check (head_seq >= 0),
    head_hash     text not null default repeat('0', 64),
    head_event_id bigint,
    head_at       timestamptz,
    created_at    timestamptz not null default now(),
    constraint audit_chains_scope_key unique nulls not distinct (org_id, workspace_id),
    constraint audit_chains_org_key unique (org_id, id),
    constraint audit_chains_workspace_fk foreign key (org_id, workspace_id) references workspaces (org_id, id)
);

create table audit_events (
    id                bigint generated always as identity,
    created_at        timestamptz not null,
    chain_id          uuid not null,
    seq               bigint not null check (seq > 0),
    org_id            uuid not null,
    workspace_id      uuid,
    actor_id          uuid,
    action            text not null,
    target_type       text,
    target_id         text,
    meta              jsonb not null default '{}'::jsonb,
    severity          text not null default 'info'
                      check (severity in ('info', 'notice', 'warning', 'break_glass', 'critical')),
    request_id        uuid,
    payload_ct_sha256 text,
    payload_key_id    bigint,
    prev_hash         text not null,
    hash              text not null,
    primary key (id, created_at),
    check ((payload_ct_sha256 is null) = (payload_key_id is null))
) partition by range (created_at);
create index audit_events_chain on audit_events (chain_id, seq);
create index audit_events_org on audit_events (org_id, id);
create index audit_events_workspace on audit_events (workspace_id, id);
create index audit_events_actor on audit_events (actor_id, id);

create table audit_payloads (
    event_id   bigint not null,
    created_at timestamptz not null,
    chain_id   uuid not null,
    key_id     bigint not null references audit_keys (id),
    ciphertext bytea not null,
    primary key (event_id, created_at)
) partition by range (created_at);

-- Event IDs stay unique across the archive and the new table.
do $$
declare
    v_next bigint := coalesce((select max(id) from audit_events_mvp), 0) + 1;
begin
    execute format('alter table audit_events alter column id restart with %s', v_next);
end
$$;

drop table audit_checkpoints;
create table audit_checkpoints (
    id           bigint generated always as identity primary key,
    chain_id     uuid not null,
    org_id       uuid not null,
    first_seq    bigint,
    last_seq     bigint not null check (last_seq >= 0),
    last_hash    text not null,
    range_start  timestamptz,
    range_end    timestamptz,
    reason       text not null check (reason in ('hourly', 'partition_detach', 'legacy_close', 'manual')),
    anchor_ref   text,
    created_at   timestamptz not null default now(),
    unique (chain_id, last_seq, reason),
    constraint audit_checkpoints_chain_fk foreign key (org_id, chain_id) references audit_chains (org_id, id)
);
create index audit_checkpoints_start on audit_checkpoints (chain_id, last_seq)
    where reason in ('partition_detach', 'legacy_close');

-- ---------------------------------------------------------------------------------------------------------------
-- 3. Close each organization's MVP chain: its control chain starts from the archive's last hash
-- ---------------------------------------------------------------------------------------------------------------
with heads as (
    select distinct on (e.org_id) e.org_id, e.id as last_id, e.hash
    from audit_events_mvp e
    where exists (select 1 from organizations o where o.id = e.org_id)
    order by e.org_id, e.id desc
),
spans as (
    select org_id, min(created_at) as first_at, max(created_at) as last_at from audit_events_mvp group by org_id
),
chains as (
    insert into audit_chains (org_id, workspace_id, head_seq, head_hash)
    select h.org_id, null, 0, h.hash from heads h
    returning id, org_id, head_hash
)
insert into audit_checkpoints (chain_id, org_id, first_seq, last_seq, last_hash, range_start, range_end, reason,
                               anchor_ref)
select c.id, c.org_id, 0, 0, c.head_hash, s.first_at, s.last_at, 'legacy_close',
       'audit_events_mvp:' || h.last_id
from chains c join heads h on h.org_id = c.org_id join spans s on s.org_id = c.org_id;

alter table audit_chains enable row level security;
alter table audit_chains force row level security;
alter table audit_events enable row level security;
alter table audit_events force row level security;
alter table audit_payloads enable row level security;
alter table audit_payloads force row level security;
alter table audit_checkpoints enable row level security;
alter table audit_checkpoints force row level security;
