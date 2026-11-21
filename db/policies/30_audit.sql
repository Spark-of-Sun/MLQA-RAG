-- Audit chain (blueprint 13): one SHA-256 chain per organization, append-only. Re-applied on every migrate.

create or replace function audit_reject_change() returns trigger
    language plpgsql
as $$ begin raise exception 'audit_events is append-only'; end $$;

create or replace trigger audit_no_update before update or delete on audit_events
    for each row execute function audit_reject_change();
create or replace trigger audit_no_truncate before truncate on audit_events
    for each statement execute function audit_reject_change();

create or replace function audit_material(
    p_org uuid, p_ws uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text,
    p_payload jsonb, p_ts timestamptz, p_prev text
) returns text
    language sql stable
as $$
    select concat_ws('|', p_org::text, coalesce(p_ws::text, ''), coalesce(p_actor::text, ''), p_action,
                     coalesce(p_target_type, ''), coalesce(p_target_id, ''), p_payload::text,
                     to_char(p_ts at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), p_prev)
$$;

-- Serialized per organization by an advisory lock, so chain order equals id order.
create or replace function audit_append(
    p_org uuid, p_ws uuid, p_actor uuid, p_action text, p_target_type text, p_target_id text, p_payload jsonb
) returns bigint
    language plpgsql security definer set search_path = public, pg_temp
as $$
declare
    v_prev text;
    v_ts   timestamptz := clock_timestamp();
    v_hash text;
    v_id   bigint;
    v_body jsonb := coalesce(p_payload, '{}'::jsonb);
begin
    perform pg_advisory_xact_lock(hashtextextended('audit:' || p_org::text, 0));
    select hash into v_prev from audit_events where org_id = p_org order by id desc limit 1;
    v_prev := coalesce(v_prev, repeat('0', 64));
    v_hash := encode(sha256(convert_to(
        audit_material(p_org, p_ws, p_actor, p_action, p_target_type, p_target_id, v_body, v_ts, v_prev),
        'UTF8')), 'hex');
    insert into audit_events (org_id, workspace_id, actor_id, action, target_type, target_id, payload,
                              created_at, prev_hash, hash)
    values (p_org, p_ws, p_actor, p_action, p_target_type, p_target_id, v_body, v_ts, v_prev, v_hash)
    returning id into v_id;
    return v_id;
end
$$;

-- Recompute an organization's chain; report the first event whose link or hash does not match.
create or replace function audit_verify(p_org uuid) returns table (ok boolean, checked bigint, first_bad_id bigint)
    language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
    r      audit_events;
    v_prev text := repeat('0', 64);
    n      bigint := 0;
begin
    for r in select * from audit_events where org_id = p_org order by id loop
        n := n + 1;
        if r.prev_hash <> v_prev or r.hash <> encode(sha256(convert_to(
            audit_material(r.org_id, r.workspace_id, r.actor_id, r.action, r.target_type, r.target_id,
                           r.payload, r.created_at, r.prev_hash), 'UTF8')), 'hex') then
            return query select false, n, r.id;
            return;
        end if;
        v_prev := r.hash;
    end loop;
    return query select true, n, null::bigint;
end
$$;
