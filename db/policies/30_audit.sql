-- Audit chains (blueprint 13.3, KD-10, DEV-18; R-61.1, R-61.4). Re-applied on every migrate.
--
-- One SHA-256 chain per workspace and one control chain per organization (audit_chains.workspace_id null). Every
-- event goes through audit_append, which takes a transaction-level advisory lock for its chain, locks the chain head,
-- links the event to the head (hash = SHA-256 of the canonical event, prev_hash included) and advances the head, so
-- two writers can never fork a chain. Events and payloads are partitioned by calendar month (UTC); the partitions are
-- created ahead of time by audit_ensure_partitions (here, on every migrate, and by the audit worker). UPDATE, DELETE
-- and TRUNCATE are rejected by trigger on every audit table; audit_chains only moves its head forward.
-- Verification, checkpoints, anchors, detach and the public-key lookup are in 31_audit_sealed.sql.

create or replace function audit_reject_change() returns trigger
    language plpgsql
as $$ begin raise exception '% is append-only', tg_table_name; end $$;

do $$
declare
    t text;
begin
    foreach t in array array['audit_events', 'audit_payloads', 'audit_checkpoints'] loop
        execute format('create or replace trigger audit_no_update before update or delete on %I'
                       ' for each row execute function audit_reject_change()', t);
        execute format('create or replace trigger audit_no_truncate before truncate on %I'
                       ' for each statement execute function audit_reject_change()', t);
    end loop;
end
$$;
create or replace trigger audit_no_delete before delete on audit_chains
    for each row execute function audit_reject_change();
create or replace trigger audit_no_truncate before truncate on audit_chains
    for each statement execute function audit_reject_change();

create or replace function audit_partition_name(p_table text, p_month date) returns text
    language sql immutable
as $$ select format('%s_%s', p_table, to_char(p_month, 'YYYY_MM')) $$;

-- Monthly partitions of audit_events and audit_payloads from p_from's month, p_months ahead. Idempotent. A partition
-- gets FORCE RLS and the TRUNCATE trigger at once (row triggers are inherited from the parent; TRUNCATE ones are not).
create or replace function audit_ensure_partitions(p_from date default null, p_months int default 3)
    returns int
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    v_month date;
    v_tbl   text;
    v_name  text;
    n       int := 0;
begin
    for i in 0 .. greatest(p_months, 1) - 1 loop
        v_month := (date_trunc('month', coalesce(p_from, (now() at time zone 'UTC')::date)::timestamp)
                    + make_interval(months => i))::date;
        foreach v_tbl in array array['audit_events', 'audit_payloads'] loop
            v_name := audit_partition_name(v_tbl, v_month);
            continue when to_regclass(v_name) is not null;
            execute format('create table %I partition of %I for values from (%L) to (%L)', v_name, v_tbl,
                           v_month::timestamp at time zone 'UTC',
                           (v_month + interval '1 month')::timestamp at time zone 'UTC');
            execute format('alter table %I enable row level security', v_name);
            execute format('alter table %I force row level security', v_name);
            execute format('create trigger audit_no_truncate before truncate on %I'
                           ' for each statement execute function audit_reject_change()', v_name);
            n := n + 1;
        end loop;
    end loop;
    return n;
end
$$;

-- The canonical event: a JSON array, so no field can run into the next one.
create or replace function audit_material(
    p_chain uuid, p_seq bigint, p_org uuid, p_ws uuid, p_actor uuid, p_action text, p_target_type text,
    p_target_id text, p_meta jsonb, p_severity text, p_request uuid, p_payload_sha256 text, p_key_id bigint,
    p_ts timestamptz, p_prev text
) returns text
    language sql stable
as $$
    select jsonb_build_array('v3', p_chain, p_seq, p_org, p_ws, p_actor, p_action, p_target_type, p_target_id,
                             p_meta, p_severity, p_request, p_payload_sha256, p_key_id,
                             to_char(p_ts at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), p_prev)::text
$$;

create or replace function audit_event_hash(r audit_events) returns text
    language sql stable
as $$
    select encode(sha256(convert_to(audit_material(
        r.chain_id, r.seq, r.org_id, r.workspace_id, r.actor_id, r.action, r.target_type, r.target_id, r.meta,
        r.severity, r.request_id, r.payload_ct_sha256, r.payload_key_id, r.created_at, r.prev_hash), 'UTF8')), 'hex')
$$;

-- Append one event to the chain of (p_org, p_ws); p_ws null is the organization control chain. p_payload is the
-- HPKE ciphertext sealed by the writer to the active audit key p_key_id of that chain and month (lmqa_audit.append);
-- only its SHA-256 enters the chain, so shredding the month's key leaves the chain verifiable (R-60.4).
create or replace function audit_append(
    p_org uuid, p_ws uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text, p_meta jsonb,
    p_severity text default 'info', p_request uuid default null, p_payload bytea default null,
    p_key_id bigint default null
) returns bigint
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    v_chain audit_chains;
    v_ts    timestamptz;
    v_month date;
    v_seq   bigint;
    v_sha   text;
    v_hash  text;
    v_id    bigint;
    v_meta  jsonb := coalesce(p_meta, '{}'::jsonb);
    v_sev   text := coalesce(p_severity, 'info');
begin
    if (p_payload is null) <> (p_key_id is null) then
        raise exception 'audit_append: a sealed payload and its audit key go together' using errcode = '22023';
    end if;
    if p_payload is not null and length(p_payload) < 48 then  -- HPKE encapsulated key (32) + AEAD tag (16)
        raise exception 'audit_append: payload must be sealed' using errcode = '22023';
    end if;
    -- One writer per chain (R-61.1). Transaction-level: never a session lock on the pooled request path (4.8).
    perform pg_advisory_xact_lock(hashtextextended('audit:' || p_org::text || ':' || coalesce(p_ws::text, 'control'), 0));
    v_ts := clock_timestamp();
    v_month := date_trunc('month', v_ts at time zone 'UTC')::date;
    if to_regclass(audit_partition_name('audit_events', v_month)) is null then
        raise exception 'audit_append: no audit partition for %; run audit_ensure_partitions()', v_month
            using errcode = '55000';
    end if;
    if p_key_id is not null and not exists (
        select 1 from audit_keys k
        where k.id = p_key_id and k.org_id = p_org and k.workspace_id is not distinct from p_ws
          and k.state = 'active'
          -- a payload sealed just before midnight UTC on the last day of a month is still accepted
          and k.month in (v_month, date_trunc('month', (v_ts - interval '5 minutes') at time zone 'UTC')::date)
    ) then
        raise exception 'audit_append: payload is not sealed to the active audit key of this chain and month'
            using errcode = '22023';
    end if;
    select * into v_chain from audit_chains c
    where c.org_id = p_org and c.workspace_id is not distinct from p_ws
    for update;
    if not found then
        insert into audit_chains (org_id, workspace_id) values (p_org, p_ws) returning * into v_chain;
    end if;
    v_seq := v_chain.head_seq + 1;
    if p_payload is not null then
        v_sha := encode(sha256(p_payload), 'hex');
    end if;
    v_hash := encode(sha256(convert_to(audit_material(
        v_chain.id, v_seq, p_org, p_ws, p_actor, p_action, p_target_type, p_target_id, v_meta, v_sev, p_request,
        v_sha, p_key_id, v_ts, v_chain.head_hash), 'UTF8')), 'hex');
    insert into audit_events (created_at, chain_id, seq, org_id, workspace_id, actor_id, action, target_type,
                              target_id, meta, severity, request_id, payload_ct_sha256, payload_key_id, prev_hash,
                              hash)
    values (v_ts, v_chain.id, v_seq, p_org, p_ws, p_actor, p_action, p_target_type, p_target_id, v_meta, v_sev,
            p_request, v_sha, p_key_id, v_chain.head_hash, v_hash)
    returning id into v_id;
    if p_payload is not null then
        insert into audit_payloads (event_id, created_at, chain_id, key_id, ciphertext)
        values (v_id, v_ts, v_chain.id, p_key_id, p_payload);
    end if;
    update audit_chains set head_seq = v_seq, head_hash = v_hash, head_event_id = v_id, head_at = v_ts
    where id = v_chain.id;
    return v_id;
end
$$;

select audit_ensure_partitions(null, 3);
