-- Least-privilege grants (blueprint 9.2, 10.3, 16.3, G1.2). Re-applied on every migrate.
-- Roles themselves are created by libs/lmqa_db/migrate.py (they need passwords from settings):
--   lmqa_owner (schema owner, migrations only), policy_helper (NOLOGIN helper owner), lmqa_app (MVP data plane),
--   svc_* (one per service). All are NOBYPASSRLS. lmqa_system is removed (DEV-13): migrate drops it, and the block
--   below only acts on a cluster where it still held privileges elsewhere and was left NOLOGIN instead.

revoke all on all tables in schema public from public;
revoke all on function app_active_workspace(), app_active_role(), app_share_target_ok(uuid), app_owns_document(uuid),
    audit_verify(uuid),
    audit_append(uuid, uuid, uuid, text, text, text, jsonb, text, uuid, bytea, bigint) from public;
grant usage on schema public to lmqa_app;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'lmqa_system') then
        revoke all on all tables in schema public from lmqa_system;
        revoke all on all functions in schema public from lmqa_system;
        revoke all on schema public from lmqa_system;
    end if;
end
$$;

-- lmqa_app: the data plane. Content tables only, always under row-level security.
revoke all on all tables in schema public from lmqa_app;
grant select, insert, delete on documents to lmqa_app;
grant select, insert on document_shares to lmqa_app;
grant select on chunks to lmqa_app;
grant select, insert on queries, retrieval_records to lmqa_app;
grant select, insert, update (title_ct, updated_at), delete on conversations to lmqa_app;
-- Field encryption (lmqa_keys.FieldCipher): keys are read under RLS; a document key is created with its document,
-- a daily cache key on first use.
grant select on org_keys, workspace_keys to lmqa_app;
grant select, insert on doc_keys, cache_keys to lmqa_app;

grant execute on function app_user_id(), app_active_workspace(), app_active_role(), app_share_target_ok(uuid),
    app_owns_document(uuid) to lmqa_app;
-- Audit writers: audit_append (the only write path) and the public half of the chain's audit key, to seal payloads.
grant execute on function audit_append(uuid, uuid, uuid, text, text, text, jsonb, text, uuid, bytea, bigint),
    audit_public_key(uuid, uuid, date) to lmqa_app;

-- ---------------------------------------------------------------------------------------------------------------
-- Production service roles (blueprint 9.2, 16.3). Each is NOBYPASSRLS and owns nothing; FORCE RLS and the policies
-- in db/policies decide rows, these grants decide tables and columns. Applied only for roles that exist.
-- ---------------------------------------------------------------------------------------------------------------
revoke all on schema ops from public;

do $$
declare
    helpers text := 'app_user_id(), app_active_workspace(), app_active_role(), app_share_target_ok(uuid), '
        'app_owns_document(uuid), app_walled(uuid), app_grant_tier(uuid), app_emergency_cap(uuid), '
        'app_break_glass_active(), app_operation(), app_upload_ceiling(text, uuid), '
        'app_can_read(uuid, uuid, text, uuid, smallint, uuid), app_access_basis(uuid, uuid, text, uuid, smallint, uuid), '
        'app_boot_self_test(), app_principal_version(), app_vector_scope(), app_super_admin_org(), app_active_org()';
    writers text := 'audit_append(uuid, uuid, uuid, text, text, text, jsonb, text, uuid, bytea, bigint), '
        'audit_public_key(uuid, uuid, date)';
    -- The audit service only: verification, checkpoints, anchors, partition maintenance and retention detach.
    audit_ops text := 'audit_verify(uuid), audit_verify_chain(uuid), audit_checkpoint(uuid, bigint, text, text), '
        'audit_anchor_leaves(timestamptz), audit_event_hash(audit_events), audit_month_heads(date), '
        'audit_detach_month(date, text), audit_ensure_partitions(date, int)';
    internal text := 'audit_material(uuid, bigint, uuid, uuid, uuid, text, text, text, jsonb, text, uuid, text, '
        'bigint, timestamptz, text), audit_partition_name(text, date)';
    r text;
begin
    execute format('revoke all on function %s from public', helpers);
    execute format('revoke all on function %s from public', writers);
    execute format('revoke all on function %s from public', audit_ops);
    execute format('revoke all on function %s from public', internal);
    revoke all on function app_compute_scope_hash(uuid), app_bump_scope(uuid) from public;
    -- The transition trigger functions (db/migrations/0010_lifecycle_machines.sql) revoke PUBLIC themselves.
    revoke all on function app_ingest_pending(), app_ingest_principal(uuid), app_workspace_people(uuid[]) from public;
    -- The MVP data-plane role gets the helpers so the policies evaluate for it.
    execute format('grant execute on function %s to policy_helper', helpers);  -- helpers call each other
    execute format('grant execute on function %s to lmqa_app', helpers);
    execute format('grant execute on function %s to lmqa_app', writers);
    grant select on state_transitions to lmqa_app;
    grant update (title_ct, updated_at, visibility, matter_id, tier, lifecycle, legal_hold, retention_until)
        on documents to lmqa_app;
    grant select, insert on query_segments to lmqa_app;
    grant update (state, released_sha256, result_ct, outcome, model, tokens_in, tokens_out, latency_ms)
        on queries to lmqa_app;
    grant execute on function app_workspace_people(uuid[]) to lmqa_app;

    foreach r in array array['svc_gateway', 'svc_identity', 'svc_ingestion', 'svc_retrieval', 'svc_generation',
                             'svc_validator', 'svc_audit_reader', 'svc_reconciler', 'svc_ops', 'ops_metadata_ro'] loop
        if not exists (select 1 from pg_roles where rolname = r) then
            continue;
        end if;
        execute format('revoke all on all tables in schema public from %I', r);
        execute format('revoke all on all tables in schema ops from %I', r);
        execute format('grant usage on schema public to %I', r);
        execute format('grant select on state_transitions to %I', r);
        execute format('grant execute on function app_boot_self_test() to %I', r);  -- every service runs it (G1.3)
        if r not in ('svc_reconciler', 'ops_metadata_ro', 'svc_audit_reader') then
            execute format('grant execute on function %s to %I', helpers, r);
            execute format('grant execute on function %s to %I', writers, r);
        end if;
    end loop;

    if exists (select 1 from pg_roles where rolname = 'svc_gateway') then
        grant select on principal_v to svc_gateway;
        grant select, insert, update, delete on idempotency_keys to svc_gateway;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_identity') then
        grant select, insert, update, delete on users, organizations, workspaces, join_codes,
            join_attempts, matters, matter_grants, matter_walls, access_exceptions, break_glass_sessions,
            governance_requests, governance_approvals, org_keys, workspace_keys, quotas, audit_keys,
            provisioning_sagas, notifications, review_tasks, alerts, step_up_events, auth0_role_snapshots
            to svc_identity;
        grant select, insert on platform_keys to svc_identity;
        -- No role-update path (R-1 criterion 8): identity, role and scope columns of a membership are never
        -- updatable; a different role means a removed membership and a new one. A trigger refuses it for the owner.
        grant select, insert, delete on memberships to svc_identity;
        grant update (status, decided_at, approver_id, state_reason, principal_version, scope_version, scope_hash,
                      owner_linked, co_owner) on memberships to svc_identity;
        grant select on workspace_usage, principal_v to svc_identity;
        grant execute on function app_compute_scope_hash(uuid), app_bump_scope(uuid) to svc_identity;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_ingestion') then
        grant select, insert, delete on documents, chunks to svc_ingestion;
        grant update (status, lifecycle, error, notes, page_count, chunk_count, structure, updated_at,
                      current_version, content_sha256) on documents to svc_ingestion;
        grant update (embedding, embedding_model, embedding_version) on chunks to svc_ingestion;
        grant select, insert, update on document_versions, doc_keys to svc_ingestion;
        grant select on workspace_keys, org_keys, document_shares to svc_ingestion;
        grant insert on index_outbox, deletion_tombstones to svc_ingestion;
        grant select, insert, delete on embedding_cache to svc_ingestion;
        grant execute on function app_ingest_pending(), app_ingest_principal(uuid) to svc_ingestion;
        grant execute on function app_workspace_people(uuid[]) to svc_ingestion;
        grant select on platform_keys to svc_ingestion;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_retrieval') then
        grant select on documents, chunks, document_shares, doc_keys, workspace_keys, org_keys to svc_retrieval;
        grant select, insert on queries, retrieval_records to svc_retrieval;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_gateway') then
        grant select, insert on query_segments to svc_gateway;
        grant select on queries to svc_gateway;
        grant update (state, released_sha256, result_ct, outcome, model, tokens_in, tokens_out, latency_ms)
            on queries to svc_gateway;
        grant select on org_keys, workspace_keys to svc_gateway;
        grant select, insert on cache_keys to svc_gateway;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_generation') then
        grant select on retrieval_records, queries, chunks, documents, doc_keys, workspace_keys, org_keys
            to svc_generation;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_validator') then
        grant select on retrieval_records, queries, chunks, documents, doc_keys, workspace_keys, org_keys
            to svc_validator;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_audit_reader') then
        grant select on audit_events, audit_payloads, audit_chains, audit_keys to svc_audit_reader;
        grant select (id, email_ct, name_ct, email_blind_index) on users to svc_audit_reader;  -- actor labels, email search
        grant select on platform_keys, org_keys to svc_audit_reader;  -- open labels; unwrap audit private keys
        grant select, insert on audit_checkpoints, audit_anchors to svc_audit_reader;
        execute format('grant execute on function %s to svc_audit_reader', audit_ops);
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_reconciler') then
        grant select (id, org_id, workspace_id, document_id, version, visibility, matter_id, tier, owner_id,
                      embedding_version, text_sha256) on chunks to svc_reconciler;
        grant select (id, org_id, workspace_id, visibility, matter_id, tier, owner_id, lifecycle, current_version)
            on documents to svc_reconciler;
        grant select, update on index_outbox to svc_reconciler;
    end if;
    if exists (select 1 from pg_roles where rolname = 'svc_ops') then
        grant usage on schema ops to svc_ops;
        grant select, insert, update on ops.operator_accounts, ops.operator_access_grants, ops.security_holds
            to svc_ops;
        grant select, insert, update on governance_requests, governance_approvals to svc_ops;
        grant execute on function audit_append(uuid, uuid, uuid, text, text, text, jsonb, text, uuid, bytea, bigint),
            audit_public_key(uuid, uuid, date) to svc_ops;
    end if;
    if exists (select 1 from pg_roles where rolname = 'ops_metadata_ro') then
        grant usage on schema ops to ops_metadata_ro;
        grant select on ops.operator_access_grants, workspace_usage to ops_metadata_ro;
    end if;
end
$$;
