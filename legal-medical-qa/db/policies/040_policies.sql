-- Row-level security (doc 10.3, 5.3, 5.4). FORCE binds even the table owner.
-- Every policy reads context through app_*() which use NULLIF, so an unset context is NULL
-- and matches no row (fail closed, DEF-52).

-- Upload ceiling (doc 5.5): an uploader may not set a tier above their own ceiling on the matter.
CREATE FUNCTION app_may_upload(p_matter uuid, p_tier integer) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$
BEGIN
  IF app_user() IS NULL OR app_ws() IS NULL OR app_role() NOT IN ('admin', 'tenant') THEN
    RETURN false;
  END IF;
  IF NOT app_actor_active() THEN
    RETURN false;
  END IF;
  IF p_matter IS NULL THEN
    RETURN true;
  END IF;
  IF EXISTS (SELECT 1 FROM matter_walls w
              WHERE w.workspace_id = app_ws() AND w.user_id = app_user() AND w.matter_id = p_matter) THEN
    RETURN false;
  END IF;
  IF app_role() = 'admin' THEN
    RETURN true;
  END IF;
  RETURN EXISTS (SELECT 1 FROM matter_grants g
                  WHERE g.workspace_id = app_ws() AND g.user_id = app_user() AND g.matter_id = p_matter
                    AND g.max_tier >= p_tier AND (g.expires_at IS NULL OR g.expires_at > now()));
END
$$;

ALTER FUNCTION app_actor_active() OWNER TO policy_helper;
ALTER FUNCTION app_can_access(uuid, uuid, text, integer) OWNER TO policy_helper;
ALTER FUNCTION app_may_upload(uuid, integer) OWNER TO policy_helper;

-- The caller's retrieval scope, derived from the transaction context alone (no identity argument).
-- Retrieval has no table access to grants, walls or sessions; it asks for this summary instead.
CREATE FUNCTION app_scope() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$
  SELECT jsonb_build_object(
    'role', app_role(),
    'active', app_actor_active(),
    'grants', coalesce((SELECT jsonb_object_agg(g.matter_id::text, g.max_tier) FROM matter_grants g
       WHERE g.workspace_id = app_ws() AND g.user_id = app_user()
         AND (g.expires_at IS NULL OR g.expires_at > now())), '{}'::jsonb),
    'walls', coalesce((SELECT jsonb_agg(w.matter_id::text) FROM matter_walls w
       WHERE w.workspace_id = app_ws() AND w.user_id = app_user()), '[]'::jsonb),
    'emergency', coalesce((SELECT jsonb_agg(DISTINCT s.matter_id::text) FROM access_sessions s
       WHERE s.workspace_id = app_ws() AND s.user_id = app_user() AND s.kind = 'emergency'
         AND s.state = 'active' AND s.expires_at > now() AND s.matter_id IS NOT NULL), '[]'::jsonb),
    'admin_private_read', (app_role() = 'admin'
       AND EXISTS (SELECT 1 FROM workspaces w WHERE w.id = app_ws() AND w.admin_can_read_private)
       AND EXISTS (SELECT 1 FROM access_sessions s WHERE s.workspace_id = app_ws() AND s.user_id = app_user()
         AND s.kind = 'break_glass' AND s.state = 'active' AND s.expires_at > now()))
  )
$$;
ALTER FUNCTION app_scope() OWNER TO policy_helper;

-- ---------------------------------------------------------------- enable and FORCE everywhere
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT LIKE 'sm\_%' LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
  END LOOP;
END
$$;

-- ---------------------------------------------------------------- policy_helper (lookups only)
-- The helper functions run as policy_helper. FORCE binds it, so each lookup table has an explicit
-- policy limited to the context user's own rows; no helper takes an identity argument.
CREATE POLICY helper_memberships ON memberships FOR SELECT TO policy_helper
  USING (user_id = app_user() AND org_id = app_org() AND workspace_id = app_ws());
CREATE POLICY helper_workspaces ON workspaces FOR SELECT TO policy_helper
  USING (id = app_ws() AND org_id = app_org());
CREATE POLICY helper_orgs ON orgs FOR SELECT TO policy_helper USING (id = app_org());
CREATE POLICY helper_walls ON matter_walls FOR SELECT TO policy_helper
  USING (workspace_id = app_ws() AND user_id = app_user());
CREATE POLICY helper_grants ON matter_grants FOR SELECT TO policy_helper
  USING (workspace_id = app_ws() AND user_id = app_user());
CREATE POLICY helper_sessions ON access_sessions FOR SELECT TO policy_helper
  USING (workspace_id = app_ws() AND user_id = app_user());

-- scope_maintainer recomputes scope_version / scope_hash from triggers (060_triggers.sql). It must
-- read ANOTHER user's grants (an admin edits a tenant's grant), so its policies are wider, but it
-- can only UPDATE the two scope columns of memberships (column grant in 050_grants.sql).
CREATE POLICY scope_grants ON matter_grants FOR SELECT TO scope_maintainer USING (true);
CREATE POLICY scope_walls ON matter_walls FOR SELECT TO scope_maintainer USING (true);
CREATE POLICY scope_sessions ON access_sessions FOR SELECT TO scope_maintainer USING (true);
CREATE POLICY scope_workspaces ON workspaces FOR SELECT TO scope_maintainer USING (true);
CREATE POLICY scope_memberships_read ON memberships FOR SELECT TO scope_maintainer USING (true);
CREATE POLICY scope_memberships_update ON memberships FOR UPDATE TO scope_maintainer USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------- principal view owner (Gateway)
CREATE POLICY principal_users ON users FOR SELECT TO principal_owner USING (true);
CREATE POLICY principal_memberships ON memberships FOR SELECT TO principal_owner USING (true);
CREATE POLICY principal_workspaces ON workspaces FOR SELECT TO principal_owner USING (true);
CREATE POLICY principal_orgs ON orgs FOR SELECT TO principal_owner USING (true);

-- ---------------------------------------------------------------- identity: control plane only
-- app_role() says whom identity is acting for: system (provisioning), super_admin, admin, tenant.
-- A Super Admin context sees organization, admin and own rows, never tenants or content (doc 5.3).
CREATE POLICY identity_orgs ON orgs FOR ALL TO svc_identity
  USING (app_is_system() OR id = app_org()) WITH CHECK (app_is_system() OR id = app_org());
CREATE POLICY identity_users ON users FOR ALL TO svc_identity USING (true) WITH CHECK (true);

CREATE POLICY identity_workspaces ON workspaces FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (app_role() = 'super_admin' OR id = app_ws())))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND (app_role() = 'super_admin' OR id = app_ws())));

-- Anyone may READ their own membership row, but only an approver (or the platform) may WRITE one:
-- otherwise a pending tenant could activate themselves if service code ever tried to let them.
CREATE POLICY identity_memberships_read ON memberships FOR SELECT TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND role IN ('super_admin', 'admin'))
     OR (app_role() = 'admin' AND workspace_id = app_ws() AND role = 'tenant')
     OR user_id = app_user())));
CREATE POLICY identity_memberships_write ON memberships FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND role IN ('super_admin', 'admin'))
     OR (app_role() = 'admin' AND workspace_id = app_ws() AND role = 'tenant'))))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND role IN ('super_admin', 'admin'))
     OR (app_role() = 'admin' AND workspace_id = app_ws() AND role = 'tenant'))));

CREATE POLICY identity_join_codes ON join_codes FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND kind IN ('org', 'successor'))
     OR (app_role() = 'admin' AND workspace_id = app_ws() AND kind = 'admin'))))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND kind IN ('org', 'successor'))
     OR (app_role() = 'admin' AND workspace_id = app_ws() AND kind = 'admin'))));

CREATE POLICY identity_join_attempts ON join_attempts FOR ALL TO svc_identity USING (true) WITH CHECK (true);

CREATE POLICY identity_governance ON governance_requests FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (
        app_role() = 'super_admin' OR (app_role() = 'admin' AND workspace_id = app_ws()))))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND (
        app_role() = 'super_admin' OR (app_role() = 'admin' AND workspace_id = app_ws()))));
CREATE POLICY identity_approvals ON governance_approvals FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND app_role() IN ('super_admin', 'admin')))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND app_role() IN ('super_admin', 'admin')));

-- Access sessions: admins manage their workspace's; a tenant manages only their own emergency one.
CREATE POLICY identity_sessions ON access_sessions FOR ALL TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND workspace_id = app_ws()
        AND (app_role() = 'admin' OR user_id = app_user())))
  WITH CHECK (app_is_system() OR (org_id = app_org() AND workspace_id = app_ws()
        AND (app_role() = 'admin' OR user_id = app_user())));

-- workspace_usage: the ONLY workspace data a Super Admin context may read.
CREATE POLICY identity_usage_read ON workspace_usage FOR SELECT TO svc_identity
  USING (app_is_system() OR (org_id = app_org() AND (app_role() = 'super_admin' OR workspace_id = app_ws())));
CREATE POLICY identity_usage_write ON workspace_usage FOR ALL TO svc_identity
  USING (app_is_system()) WITH CHECK (app_is_system());

CREATE POLICY identity_org_keys ON org_keys FOR ALL TO svc_identity
  USING (app_is_system()) WITH CHECK (app_is_system());
CREATE POLICY identity_ws_keys ON workspace_keys FOR ALL TO svc_identity
  USING (app_is_system()) WITH CHECK (app_is_system());
CREATE POLICY identity_audit_keys ON audit_keys FOR ALL TO svc_identity
  USING (app_is_system()) WITH CHECK (app_is_system());

-- Matter taxonomy and grants are managed by the workspace admin (doc 15.6).
CREATE POLICY identity_matters_read ON matters FOR SELECT TO svc_identity
  USING (org_id = app_org() AND workspace_id = app_ws() AND (
        app_role() = 'admin'
     OR (app_role() = 'tenant' AND EXISTS (
          SELECT 1 FROM matter_grants g WHERE g.matter_id = matters.id AND g.user_id = app_user()))));
CREATE POLICY identity_matters_write ON matters FOR ALL TO svc_identity
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin')
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin');
CREATE POLICY identity_grants_admin ON matter_grants FOR ALL TO svc_identity
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin')
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin');
CREATE POLICY identity_grants_self ON matter_grants FOR SELECT TO svc_identity
  USING (workspace_id = app_ws() AND user_id = app_user());
-- Walls are readable only by the workspace admin; the walled user sees only "no access" (doc 5.6).
CREATE POLICY identity_walls ON matter_walls FOR ALL TO svc_identity
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin')
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND app_role() = 'admin');

CREATE POLICY identity_idempotency ON idempotency_keys FOR ALL TO svc_identity
  USING (user_id = app_user()) WITH CHECK (user_id = app_user());
CREATE POLICY identity_tombstones ON deletion_tombstones FOR ALL TO svc_identity
  USING (org_id = app_org() OR app_is_system()) WITH CHECK (org_id = app_org() OR app_is_system());

-- ---------------------------------------------------------------- content: documents
-- Reads: the single access decision. Writes: ingestion in the owner's context.
CREATE POLICY content_documents_read ON documents FOR SELECT
  TO svc_ingestion, svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws()
         AND app_can_access(owner_user_id, matter_id, visibility, confidentiality_tier::integer));
CREATE POLICY content_documents_insert ON documents FOR INSERT TO svc_ingestion
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user()
              AND app_may_upload(matter_id, confidentiality_tier::integer));
CREATE POLICY content_documents_update ON documents FOR UPDATE TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user() AND app_actor_active())
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user()
              AND app_may_upload(matter_id, confidentiality_tier::integer));
CREATE POLICY content_documents_delete ON documents FOR DELETE TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user() AND app_actor_active());

CREATE POLICY content_versions_read ON document_versions FOR SELECT
  TO svc_ingestion, svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.doc_id));
CREATE POLICY content_versions_write ON document_versions FOR ALL TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.doc_id AND d.owner_user_id = app_user()))
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = document_versions.doc_id AND d.owner_user_id = app_user()));

-- Chunks: ingestion sees quarantined chunks (OCR review); every other reader never does (doc 11.1).
CREATE POLICY content_chunks_read_ingestion ON chunks FOR SELECT TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws()
         AND app_can_access(owner_user_id, matter_id, visibility, confidentiality_tier::integer));
CREATE POLICY content_chunks_read ON chunks FOR SELECT TO svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws() AND NOT quarantined
         AND app_can_access(owner_user_id, matter_id, visibility, confidentiality_tier::integer));
CREATE POLICY content_chunks_insert ON chunks FOR INSERT TO svc_ingestion
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user()
              AND app_may_upload(matter_id, confidentiality_tier::integer));
CREATE POLICY content_chunks_update ON chunks FOR UPDATE TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user() AND app_actor_active())
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user()
              AND app_may_upload(matter_id, confidentiality_tier::integer));
CREATE POLICY content_chunks_delete ON chunks FOR DELETE TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws() AND owner_user_id = app_user() AND app_actor_active());

-- Document keys: only for documents the caller can read, and only while the actor is active.
CREATE POLICY content_dockeys_read ON doc_keys FOR SELECT
  TO svc_ingestion, svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_actor_active()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = doc_keys.doc_id));
CREATE POLICY content_dockeys_write ON doc_keys FOR ALL TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_actor_active()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = doc_keys.doc_id AND d.owner_user_id = app_user()))
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND app_actor_active()
         AND EXISTS (SELECT 1 FROM documents d WHERE d.id = doc_keys.doc_id AND d.owner_user_id = app_user()));
CREATE POLICY content_wskeys_read ON workspace_keys FOR SELECT
  TO svc_ingestion, svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws() AND app_actor_active());
CREATE POLICY content_orgkeys_read ON org_keys FOR SELECT
  TO svc_ingestion, svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND app_actor_active());

CREATE POLICY content_outbox ON index_outbox FOR ALL TO svc_ingestion
  USING (org_id = app_org() AND workspace_id = app_ws())
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws());
CREATE POLICY content_idempotency ON idempotency_keys FOR ALL TO svc_ingestion
  USING (user_id = app_user()) WITH CHECK (user_id = app_user());
CREATE POLICY content_tombstones ON deletion_tombstones FOR ALL TO svc_ingestion
  USING (org_id = app_org()) WITH CHECK (org_id = app_org());

-- The retrieval ledger (doc 9.4, DEF-63): insert-only for retrieval; reads also scoped to the user.
CREATE POLICY ledger_insert ON retrieval_records FOR INSERT TO svc_retrieval
  WITH CHECK (org_id = app_org() AND workspace_id = app_ws() AND user_id = app_user() AND app_actor_active());
CREATE POLICY ledger_read ON retrieval_records FOR SELECT TO svc_retrieval, svc_generation, svc_validator
  USING (org_id = app_org() AND workspace_id = app_ws() AND user_id = app_user());

-- The reconciler sees IDs and index metadata of one workspace at a time (column grants hide text).
CREATE POLICY recon_documents ON documents FOR SELECT TO svc_reconciler
  USING (app_role() = 'reconciler' AND org_id = app_org() AND workspace_id = app_ws());
CREATE POLICY recon_chunks ON chunks FOR SELECT TO svc_reconciler
  USING (app_role() = 'reconciler' AND org_id = app_org() AND workspace_id = app_ws());
CREATE POLICY recon_versions ON document_versions FOR SELECT TO svc_reconciler
  USING (app_role() = 'reconciler' AND org_id = app_org() AND workspace_id = app_ws());
CREATE POLICY recon_outbox ON index_outbox FOR ALL TO svc_reconciler
  USING (app_role() = 'reconciler' AND org_id = app_org() AND workspace_id = app_ws())
  WITH CHECK (app_role() = 'reconciler' AND org_id = app_org() AND workspace_id = app_ws());

-- ---------------------------------------------------------------- audit (doc 13.5)
-- Writes happen only inside audit_append (owned by audit_definer). No service holds
-- INSERT/UPDATE/DELETE; a trigger additionally rejects UPDATE and DELETE.
CREATE POLICY audit_definer_event_insert ON audit_event FOR INSERT TO audit_definer WITH CHECK (true);
CREATE POLICY audit_definer_event_read ON audit_event FOR SELECT TO audit_definer USING (true);
CREATE POLICY audit_definer_payload_insert ON audit_payload FOR INSERT TO audit_definer WITH CHECK (true);

CREATE POLICY audit_reader_events ON audit_event FOR SELECT TO svc_audit_reader
  USING (app_is_system() OR (org_id = app_org() AND (
        (app_role() = 'super_admin' AND scope IN ('org', 'admin'))
     OR (app_role() = 'admin' AND workspace_id = app_ws())
     OR (app_role() = 'tenant' AND workspace_id = app_ws()
         AND (actor_id = app_user() OR target = 'user:' || app_user()::text)))));
-- Super Admins never read payloads; tenants read only their own; admins their workspace's.
CREATE POLICY audit_reader_payloads ON audit_payload FOR SELECT TO svc_audit_reader
  USING (org_id = app_org() AND workspace_id = app_ws() AND (
        app_role() = 'admin'
     OR (app_role() = 'tenant' AND EXISTS (
          SELECT 1 FROM audit_event e WHERE e.id = audit_payload.event_id AND e.actor_id = app_user()))));
CREATE POLICY audit_reader_keys ON audit_keys FOR SELECT TO svc_audit_reader
  USING (app_is_system() OR org_id = app_org());
CREATE POLICY audit_reader_anchor ON audit_anchor FOR ALL TO svc_audit_reader USING (true) WITH CHECK (true);
-- Destroying a month's private key (crypto-shred) is the only write the audit reader may make to
-- audit_keys, and only in the platform's system context (column grant in 050_grants.sql).
CREATE POLICY audit_reader_keys_shred ON audit_keys FOR UPDATE TO svc_audit_reader
  USING (app_is_system()) WITH CHECK (app_is_system());
-- Writers only need the PUBLIC half of the month's key to seal payloads (doc 13.2).
CREATE POLICY audit_keys_public ON audit_keys FOR SELECT
  TO svc_gateway, svc_ingestion, svc_retrieval, svc_generation, svc_validator, svc_identity
  USING (org_id = app_org() AND workspace_id = app_ws());
