-- Privileges (doc 10.3, 16.3). Least privilege per service; RLS then narrows rows.
-- No PUBLIC grants anywhere (G1.2).

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

-- The only relation the Gateway can read: no grants, walls or content (doc 10.3, DEF-49).
CREATE VIEW principal_v AS
SELECT u.id                AS user_id,
       u.auth0_sub         AS auth0_sub,
       m.org_id            AS org_id,
       o.auth0_org_id      AS auth0_org_id,
       m.workspace_id      AS workspace_id,
       m.role              AS role,
       m.state             AS membership_state,
       w.state             AS workspace_state,
       o.state             AS org_state,
       m.principal_version AS principal_version,
       m.scope_version     AS scope_version,
       m.scope_hash        AS scope_hash,
       m.owner_linked      AS owner_linked,
       u.auth_strength_last AS auth_strength_last,
       w.delivery_mode     AS delivery_mode,
       w.on_fail           AS on_fail
  FROM memberships m
  JOIN users u ON u.id = m.user_id
  JOIN orgs o ON o.id = m.org_id
  LEFT JOIN workspaces w ON w.id = m.workspace_id;
ALTER VIEW principal_v OWNER TO principal_owner;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY[
    'policy_helper', 'principal_owner', 'audit_definer', 'scope_maintainer',
    'svc_gateway', 'svc_identity', 'svc_ingestion', 'svc_retrieval', 'svc_generation',
    'svc_validator', 'svc_audit_reader', 'svc_reconciler', 'svc_ops', 'ops_metadata_ro'
  ] LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', r);
    -- Policies call these as the invoking role.
    EXECUTE format('GRANT EXECUTE ON FUNCTION app_org(), app_ws(), app_user(), app_role(), app_is_system() TO %I', r);
  END LOOP;
  FOREACH r IN ARRAY ARRAY[
    'svc_ingestion', 'svc_retrieval', 'svc_generation', 'svc_validator', 'svc_reconciler'
  ] LOOP
    EXECUTE format('GRANT EXECUTE ON FUNCTION app_can_access(uuid, uuid, text, integer), '
                   'app_may_upload(uuid, integer), app_actor_active() TO %I', r);
  END LOOP;
END
$$;

GRANT EXECUTE ON FUNCTION app_scope() TO svc_retrieval;

-- helper roles: lookups only
GRANT SELECT ON memberships, workspaces, orgs, matter_walls, matter_grants, access_sessions TO policy_helper;
GRANT SELECT ON users, memberships, workspaces, orgs TO principal_owner;
GRANT SELECT ON matter_grants, matter_walls, access_sessions, workspaces TO scope_maintainer;
GRANT SELECT, UPDATE (scope_version, scope_hash) ON memberships TO scope_maintainer;

-- Gateway: principal_v and the public half of audit keys. Nothing else.
GRANT SELECT ON principal_v TO svc_gateway;

-- Identity: control-plane tables only. No documents, chunks, ledger or audit payloads.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  orgs, users, workspaces, memberships, join_codes, join_attempts, governance_requests,
  governance_approvals, access_sessions, workspace_usage, org_keys, workspace_keys,
  matters, matter_grants, matter_walls, idempotency_keys, deletion_tombstones
  TO svc_identity;
-- Identity creates a workspace's first key pair but can never read a wrapped private key back:
-- only the audit service unwraps (doc 4.2, 13.2).
GRANT INSERT ON audit_keys TO svc_identity;
GRANT SELECT (id, org_id, workspace_id, month, public_key) ON audit_keys TO svc_identity;

-- Ingestion: documents, versions, chunks, keys, outbox.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  documents, document_versions, chunks, doc_keys, index_outbox, idempotency_keys, deletion_tombstones
  TO svc_ingestion;
GRANT SELECT ON workspace_keys, org_keys TO svc_ingestion;

-- Retrieval, generation, validator: read content under RLS. Retrieval alone writes the ledger.
GRANT SELECT ON documents, document_versions, chunks, doc_keys, workspace_keys, org_keys
  TO svc_retrieval, svc_generation, svc_validator;
GRANT SELECT ON retrieval_records TO svc_retrieval, svc_generation, svc_validator;
GRANT INSERT ON retrieval_records TO svc_retrieval;

-- Writers see only the PUBLIC half of an audit key (doc 13.2).
GRANT SELECT (id, org_id, workspace_id, month, public_key) ON audit_keys
  TO svc_gateway, svc_ingestion, svc_retrieval, svc_generation, svc_validator;

-- Audit reader: events, payloads, anchors, private keys. It is the only role that can unwrap.
GRANT SELECT ON audit_event, audit_payload, audit_keys TO svc_audit_reader;
GRANT SELECT, INSERT ON audit_anchor TO svc_audit_reader;
GRANT UPDATE (wrapped_private_key) ON audit_keys TO svc_audit_reader;

-- Reconciler: column-level SELECT on IDs and index metadata. No text columns (doc 10.3).
GRANT SELECT (id, org_id, workspace_id, status, current_version, matter_id, visibility,
              confidentiality_tier, owner_user_id) ON documents TO svc_reconciler;
GRANT SELECT (id, org_id, workspace_id, doc_id, doc_version, ordinal, owner_user_id, matter_id,
              visibility, confidentiality_tier, quarantined, is_current, payload_version)
  ON chunks TO svc_reconciler;
GRANT SELECT (doc_id, org_id, workspace_id, version, index_state, embedding_version)
  ON document_versions TO svc_reconciler;
GRANT SELECT, INSERT, UPDATE ON index_outbox TO svc_reconciler;

-- audit_definer owns audit_append: the only writer of audit tables (doc 13.3).
GRANT SELECT, INSERT ON audit_event TO audit_definer;
GRANT INSERT ON audit_payload TO audit_definer;
