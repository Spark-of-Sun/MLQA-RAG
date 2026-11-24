-- Sealed payloads, verification, checkpoints, anchors and partition detach (blueprint 13.1 to 13.4, KD-10; R-60.2 to
-- R-60.4, R-61.1, R-61.3, R-61.5). Re-applied on every migrate.
--
-- Writers seal a payload with HPKE (RFC 9180; lmqa_security.sealing) to the workspace-month audit public key from
-- audit_public_key before calling audit_append, so no writer can read what it wrote; only the audit service unwraps
-- the private keys (lmqa_keys.KeyRing.audit_private_key). The chain covers the SHA-256 of the ciphertext, so
-- destroying a month's private key (crypto-shredding its payloads) leaves the chain verifiable (G9.2).

-- The active public half of one chain's audit key for one month; empty when there is none (the writer fails closed).
create or replace function audit_public_key(p_org uuid, p_ws uuid, p_month date)
    returns table (key_id bigint, month date, public_key bytea)
    language sql stable security definer set search_path = public, pg_temp
as $$
    select k.id, k.month, k.public_key from audit_keys k
    where k.org_id = p_org and k.workspace_id is not distinct from p_ws
      and k.month = date_trunc('month', p_month::timestamp)::date and k.state = 'active'
$$;

-- Recompute one chain. It starts at the latest checkpoint below the first attached event (a detached partition or
-- the closed MVP chain, R-61.5), else at the zero hash; every event must carry the next seq, link to the previous
-- hash, hash to its own content, belong to the chain's scope and, if it has a payload, match the payload's SHA-256;
-- the head must be the last event, so a deleted tail is a break too.
create or replace function audit_verify_chain(p_chain uuid) returns table (ok boolean, checked bigint, first_bad_id bigint)
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    c      audit_chains;
    r      audit_events;
    v_min  bigint;
    v_next bigint;
    v_prev text;
    v_ct   bytea;
    n      bigint := 0;
begin
    select * into c from audit_chains ch where ch.id = p_chain;
    if not found then
        return query select false, 0::bigint, null::bigint;
        return;
    end if;
    select min(e.seq) into v_min from audit_events e where e.chain_id = p_chain;
    select k.last_seq, k.last_hash into v_next, v_prev
    from audit_checkpoints k
    where k.chain_id = p_chain and k.reason in ('partition_detach', 'legacy_close')
      and k.last_seq < coalesce(v_min, c.head_seq + 1)
    order by k.last_seq desc limit 1;
    v_next := coalesce(v_next, 0) + 1;
    v_prev := coalesce(v_prev, repeat('0', 64));
    for r in select * from audit_events e where e.chain_id = p_chain order by e.seq, e.id loop
        n := n + 1;
        if r.seq <> v_next or r.prev_hash <> v_prev or r.hash <> audit_event_hash(r)
           or r.org_id <> c.org_id or r.workspace_id is distinct from c.workspace_id then
            return query select false, n, r.id;
            return;
        end if;
        if r.payload_ct_sha256 is not null then
            select p.ciphertext into v_ct from audit_payloads p
            where p.event_id = r.id and p.created_at = r.created_at and p.key_id = r.payload_key_id;
            if v_ct is null or encode(sha256(v_ct), 'hex') <> r.payload_ct_sha256 then
                return query select false, n, r.id;
                return;
            end if;
        end if;
        v_prev := r.hash;
        v_next := v_next + 1;
    end loop;
    if c.head_seq <> v_next - 1 or c.head_hash <> v_prev then
        return query select false, n, c.head_event_id;
        return;
    end if;
    return query select true, n, null::bigint;
end
$$;

-- Every chain of an organization (its workspaces and its control chain); the first break wins. An event outside
-- every chain of its organization is a break too.
create or replace function audit_verify(p_org uuid) returns table (ok boolean, checked bigint, first_bad_id bigint)
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    ch      record;
    v       record;
    total   bigint := 0;
    v_stray bigint;
begin
    for ch in select c.id from audit_chains c where c.org_id = p_org order by c.workspace_id nulls first, c.id loop
        select * into v from audit_verify_chain(ch.id);
        total := total + v.checked;
        if not v.ok then
            return query select false, total, v.first_bad_id;
            return;
        end if;
    end loop;
    select e.id into v_stray from audit_events e
    where e.org_id = p_org
      and not exists (select 1 from audit_chains c where c.id = e.chain_id and c.org_id = e.org_id)
    limit 1;
    if v_stray is not null then
        return query select false, total, v_stray;
        return;
    end if;
    return query select true, total, null::bigint;
end
$$;

-- Hourly anchor leaves (13.4): the last event of every chain before p_end.
create or replace function audit_anchor_leaves(p_end timestamptz)
    returns table (chain_id uuid, org_id uuid, workspace_id uuid, seq bigint, hash text)
    language sql stable security definer set search_path = public, pg_temp
as $$
    select distinct on (e.chain_id) e.chain_id, e.org_id, e.workspace_id, e.seq, e.hash
    from audit_events e where e.created_at < p_end
    order by e.chain_id, e.seq desc
$$;

-- An hourly or manual checkpoint at one event (written with its anchor object reference).
create or replace function audit_checkpoint(p_chain uuid, p_seq bigint, p_reason text, p_anchor_ref text)
    returns bigint
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    v_id bigint;
begin
    if p_reason not in ('hourly', 'manual') then
        raise exception 'audit_checkpoint: reason must be hourly or manual' using errcode = '22023';
    end if;
    insert into audit_checkpoints (chain_id, org_id, last_seq, last_hash, range_end, reason, anchor_ref)
    select e.chain_id, e.org_id, e.seq, e.hash, e.created_at, p_reason, p_anchor_ref
    from audit_events e where e.chain_id = p_chain and e.seq = p_seq
    on conflict (chain_id, last_seq, reason) do nothing
    returning id into v_id;
    return v_id;
end
$$;

-- The range of every chain inside one month's partition: what a detach checkpoint records and the anchor covers.
create or replace function audit_month_heads(p_month date)
    returns table (chain_id uuid, org_id uuid, workspace_id uuid, first_seq bigint, last_seq bigint, last_hash text,
                   range_start timestamptz, range_end timestamptz)
    language sql stable security definer set search_path = public, pg_temp
as $$
    with b as (
        select date_trunc('month', p_month::timestamp) at time zone 'UTC' as lo,
               (date_trunc('month', p_month::timestamp) + interval '1 month') at time zone 'UTC' as hi
    )
    select distinct on (e.chain_id) e.chain_id, e.org_id, e.workspace_id,
           min(e.seq) over (partition by e.chain_id), e.seq, e.hash, b.lo, b.hi
    from audit_events e, b
    where e.created_at >= b.lo and e.created_at < b.hi
    order by e.chain_id, e.seq desc
$$;

-- Detach one past month for retention (R-61.5). The caller first anchors audit_month_heads(p_month) (Object Lock,
-- audit.anchor.detach_month) and passes the anchor reference; this writes one partition_detach checkpoint per chain,
-- then detaches the events and payloads partitions. Months are detached oldest first, so every chain stays
-- verifiable from its checkpoint. The detached tables keep the append-only triggers.
create or replace function audit_detach_month(p_month date, p_anchor_ref text) returns int
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    v_month date := date_trunc('month', p_month::timestamp)::date;
    v_lo    timestamptz := date_trunc('month', p_month::timestamp) at time zone 'UTC';
    v_tbl   text;
    v_name  text;
    n       int;
begin
    if coalesce(p_anchor_ref, '') = '' then
        raise exception 'audit_detach_month: anchor the checkpoints first' using errcode = '22023';
    end if;
    if v_lo + interval '1 month' > clock_timestamp() - interval '5 minutes' then
        raise exception 'audit_detach_month: % is not a past month', v_month using errcode = '22023';
    end if;
    if exists (select 1 from audit_events e where e.created_at < v_lo) then
        raise exception 'audit_detach_month: detach older months first' using errcode = '55000';
    end if;
    insert into audit_checkpoints (chain_id, org_id, first_seq, last_seq, last_hash, range_start, range_end, reason,
                                   anchor_ref)
    select h.chain_id, h.org_id, h.first_seq, h.last_seq, h.last_hash, h.range_start, h.range_end,
           'partition_detach', p_anchor_ref
    from audit_month_heads(v_month) h
    on conflict (chain_id, last_seq, reason) do nothing;
    get diagnostics n = row_count;
    foreach v_tbl in array array['audit_events', 'audit_payloads'] loop
        v_name := audit_partition_name(v_tbl, v_month);
        continue when to_regclass(v_name) is null;
        execute format('alter table %I detach partition %I', v_tbl, v_name);
        execute format('create or replace trigger audit_no_update before update or delete on %I'
                       ' for each row execute function audit_reject_change()', v_name);
        execute format('create or replace trigger audit_no_truncate before truncate on %I'
                       ' for each statement execute function audit_reject_change()', v_name);
    end loop;
    return n;
end
$$;
