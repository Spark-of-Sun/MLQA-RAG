-- audit_append: the ONLY way to write audit tables (doc 13.3). SECURITY DEFINER, owned by
-- audit_definer. It takes a per-chain transaction-level advisory lock (safe under connection
-- pooling, unlike session locks) and computes hash = H(prev_hash || canonical event).

CREATE FUNCTION audit_canonical(
  p_id uuid, p_chain text, p_seq bigint, p_org uuid, p_ws uuid, p_ts timestamptz, p_actor uuid,
  p_role text, p_action text, p_target text, p_outcome text, p_reason text, p_request uuid,
  p_scope text, p_ip inet, p_ua text, p_payload_hash bytea
) RETURNS bytea LANGUAGE sql IMMUTABLE AS
$$
  -- jsonb text output has a deterministic key order; the timestamp is formatted in UTC so the
  -- hash never depends on the session TimeZone.
  SELECT convert_to(jsonb_build_object(
    'id', p_id, 'chain', p_chain, 'seq', p_seq, 'org', p_org, 'ws', p_ws,
    'ts', to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'actor', p_actor, 'role', p_role, 'action', p_action, 'target', p_target,
    'outcome', p_outcome, 'reason', p_reason, 'request', p_request, 'scope', p_scope,
    'ip', host(p_ip), 'ua', p_ua, 'payload_hash', encode(p_payload_hash, 'hex')
  )::text, 'UTF8')
$$;

CREATE FUNCTION audit_append(
  p_chain text, p_org uuid, p_ws uuid, p_actor uuid, p_actor_role text, p_action text,
  p_target text, p_outcome text, p_reason text, p_request uuid, p_ip inet, p_ua text,
  p_scope text, p_payload bytea DEFAULT NULL, p_key_id text DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
  v_prev  bytea;
  v_seq   bigint;
  v_id    uuid := uuidv7();
  v_ts    timestamptz := clock_timestamp();
  v_phash bytea;
  v_hash  bytea;
BEGIN
  -- An event may only be written for the request's own scope (the identity service may act
  -- for the platform in 'system' context, e.g. organization provisioning).
  IF NOT app_is_system() AND (
       p_org IS DISTINCT FROM app_org()
    OR (p_ws IS NOT NULL AND p_ws IS DISTINCT FROM app_ws())) THEN
    RAISE EXCEPTION 'audit_append: event scope does not match the request context'
      USING ERRCODE = '42501';
  END IF;
  IF p_chain IS DISTINCT FROM ('org:' || p_org::text)
     AND p_chain IS DISTINCT FROM ('ws:' || coalesce(p_ws::text, '')) THEN
    RAISE EXCEPTION 'audit_append: chain does not belong to the event scope' USING ERRCODE = '22023';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_chain, 0));

  SELECT e.hash, e.seq INTO v_prev, v_seq
    FROM audit_event e WHERE e.chain_id = p_chain ORDER BY e.seq DESC LIMIT 1;
  IF NOT FOUND THEN
    v_prev := decode(repeat('00', 32), 'hex');   -- genesis
    v_seq := 0;
  END IF;
  v_seq := v_seq + 1;
  v_phash := CASE WHEN p_payload IS NULL THEN NULL ELSE sha256(p_payload) END;
  v_hash := sha256(v_prev || audit_canonical(v_id, p_chain, v_seq, p_org, p_ws, v_ts, p_actor,
      p_actor_role, p_action, p_target, p_outcome, p_reason, p_request, p_scope, p_ip, p_ua, v_phash));

  INSERT INTO audit_event (id, chain_id, seq, org_id, workspace_id, ts, actor_id, actor_role, action,
      target, outcome, reason_code, request_id, ip, user_agent, scope, prev_hash, payload_hash, hash)
  VALUES (v_id, p_chain, v_seq, p_org, p_ws, v_ts, p_actor, p_actor_role, p_action,
      p_target, p_outcome, p_reason, p_request, p_ip, p_ua, p_scope, v_prev, v_phash, v_hash);

  IF p_payload IS NOT NULL THEN
    INSERT INTO audit_payload (event_id, org_id, workspace_id, ciphertext, key_id)
    VALUES (v_id, p_org, p_ws, p_payload, coalesce(p_key_id, 'unspecified'));
  END IF;
  RETURN v_id;
END
$$;

-- Verification (doc 13.3): recomputes the whole chain. Returns the first bad sequence number,
-- or NULL when the chain is intact. The hash covers the ciphertext hash, not the plaintext, so
-- shredding a month's key never breaks verification.
CREATE FUNCTION audit_verify(p_chain text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
  e record;
  v_prev bytea := decode(repeat('00', 32), 'hex');
  v_expected_seq bigint := 1;
BEGIN
  FOR e IN SELECT * FROM audit_event WHERE chain_id = p_chain ORDER BY seq LOOP
    IF e.seq <> v_expected_seq OR e.prev_hash <> v_prev THEN
      RETURN e.seq;
    END IF;
    IF e.hash <> sha256(e.prev_hash || audit_canonical(e.id, e.chain_id, e.seq, e.org_id, e.workspace_id,
         e.ts, e.actor_id, e.actor_role, e.action, e.target, e.outcome, e.reason_code, e.request_id,
         e.scope, e.ip, e.user_agent, e.payload_hash)) THEN
      RETURN e.seq;
    END IF;
    v_prev := e.hash;
    v_expected_seq := v_expected_seq + 1;
  END LOOP;
  RETURN NULL;
END
$$;

ALTER FUNCTION audit_append(text, uuid, uuid, uuid, text, text, text, text, text, uuid, inet, text, text, bytea, text)
  OWNER TO audit_definer;
ALTER FUNCTION audit_verify(text) OWNER TO audit_definer;
-- audit_verify reads every chain; the audit_definer read policy covers it.

REVOKE ALL ON FUNCTION audit_append(text, uuid, uuid, uuid, text, text, text, text, text, uuid, inet, text, text, bytea, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_verify(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_canonical(uuid, text, bigint, uuid, uuid, timestamptz, uuid, text, text, text, text, text, uuid, text, inet, text, bytea) FROM PUBLIC;

-- Every service writes through audit_append; only the audit reader may verify.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY[
    'svc_gateway', 'svc_identity', 'svc_ingestion', 'svc_retrieval', 'svc_generation',
    'svc_validator', 'svc_audit_reader', 'svc_ops'
  ] LOOP
    EXECUTE format('GRANT EXECUTE ON FUNCTION audit_append(text, uuid, uuid, uuid, text, text, text, text, text, uuid, inet, text, text, bytea, text) TO %I', r);
  END LOOP;
END
$$;
GRANT EXECUTE ON FUNCTION audit_verify(text) TO svc_audit_reader;
GRANT EXECUTE ON FUNCTION audit_canonical(uuid, text, bigint, uuid, uuid, timestamptz, uuid, text, text, text, text, text, uuid, text, inet, text, bytea) TO audit_definer;
