-- Triggers (doc 6.1, 10.3, 11.2, 13.3). State-machine triggers are generated from
-- contracts/state-machines.yaml by the Alembic baseline; this file holds the rest.

-- A state or role change must invalidate every cached principal (doc 8.6).
CREATE FUNCTION memberships_bump_principal_version() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state OR NEW.role IS DISTINCT FROM OLD.role THEN
    NEW.principal_version := OLD.principal_version + 1;
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER memberships_bump_principal_version
  BEFORE UPDATE OF state, role ON memberships
  FOR EACH ROW EXECUTE FUNCTION memberships_bump_principal_version();

-- Roles never change in v1 (doc 5.1): removes role editing as an escalation path.
CREATE FUNCTION memberships_role_is_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.role IS DISTINCT FROM OLD.role THEN
    RAISE EXCEPTION 'membership role is immutable in v1' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER memberships_role_is_immutable
  BEFORE UPDATE OF role ON memberships
  FOR EACH ROW EXECUTE FUNCTION memberships_role_is_immutable();

-- Chunks are immutable per document version (doc 11.2). Only the access fields (kept in step with
-- the document), is_current and payload_version may change; text and identity never do.
CREATE FUNCTION chunks_guard_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF (NEW.id, NEW.org_id, NEW.workspace_id, NEW.doc_id, NEW.doc_version, NEW.ordinal,
      NEW.text_ciphertext, NEW.text_sha256, NEW.token_count, NEW.page_start, NEW.page_end,
      NEW.spans, NEW.kind, NEW.quarantined)
     IS DISTINCT FROM
     (OLD.id, OLD.org_id, OLD.workspace_id, OLD.doc_id, OLD.doc_version, OLD.ordinal,
      OLD.text_ciphertext, OLD.text_sha256, OLD.token_count, OLD.page_start, OLD.page_end,
      OLD.spans, OLD.kind, OLD.quarantined) THEN
    RAISE EXCEPTION 'chunks are immutable per document version' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER chunks_guard_immutable BEFORE UPDATE ON chunks
  FOR EACH ROW EXECUTE FUNCTION chunks_guard_immutable();

-- A legal hold blocks deletion (doc 13.8, DEF-48).
CREATE FUNCTION documents_guard_hold() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.status = 'deleting' AND OLD.status IS DISTINCT FROM 'deleting'
     AND (OLD.legal_hold OR (OLD.retention_until IS NOT NULL AND OLD.retention_until > now())) THEN
    RAISE EXCEPTION 'document is under legal hold or retention' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER documents_guard_hold BEFORE UPDATE OF status ON documents
  FOR EACH ROW EXECUTE FUNCTION documents_guard_hold();

CREATE FUNCTION documents_guard_hold_delete() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF OLD.legal_hold OR (OLD.retention_until IS NOT NULL AND OLD.retention_until > now()) THEN
    RAISE EXCEPTION 'document is under legal hold or retention' USING ERRCODE = '23514';
  END IF;
  RETURN OLD;
END
$$;
CREATE TRIGGER documents_guard_hold_delete BEFORE DELETE ON documents
  FOR EACH ROW EXECUTE FUNCTION documents_guard_hold_delete();

-- ---------------------------------------------------------------- scope_hash maintenance (DEF-49)
-- The Gateway reads scope_hash / scope_version from principal_v only; these triggers keep them
-- current whenever grants, walls, sessions or workspace flags change. Expiry timestamps are part
-- of the hash, so time passing does not change it; RLS always evaluates live time.
CREATE FUNCTION recompute_scope(p_ws uuid, p_user uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE v_hash text;
BEGIN
  IF p_ws IS NULL OR p_user IS NULL THEN
    RETURN;
  END IF;
  SELECT encode(sha256(convert_to(concat_ws('|',
    coalesce((SELECT string_agg(g.matter_id::text || ':' || g.max_tier || ':' || coalesce(g.expires_at::text, ''),
                                ',' ORDER BY g.matter_id)
                FROM matter_grants g WHERE g.workspace_id = p_ws AND g.user_id = p_user), ''),
    coalesce((SELECT string_agg(w.matter_id::text, ',' ORDER BY w.matter_id)
                FROM matter_walls w WHERE w.workspace_id = p_ws AND w.user_id = p_user), ''),
    coalesce((SELECT string_agg(s.kind || ':' || coalesce(s.matter_id::text, '') || ':' || s.expires_at::text,
                                ',' ORDER BY s.id)
                FROM access_sessions s
               WHERE s.workspace_id = p_ws AND s.user_id = p_user AND s.state = 'active'), ''),
    coalesce((SELECT w.admin_can_read_private::text FROM workspaces w WHERE w.id = p_ws), '')
  ), 'UTF8')), 'hex') INTO v_hash;
  UPDATE memberships
     SET scope_hash = v_hash, scope_version = scope_version + 1
   WHERE user_id = p_user AND workspace_id = p_ws AND scope_hash IS DISTINCT FROM v_hash;
END
$$;

CREATE FUNCTION scope_touch_user() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM recompute_scope(OLD.workspace_id, OLD.user_id);
  END IF;
  IF TG_OP IN ('UPDATE', 'INSERT') THEN
    PERFORM recompute_scope(NEW.workspace_id, NEW.user_id);
  END IF;
  RETURN NULL;
END
$$;

CREATE FUNCTION scope_touch_workspace() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE v_admin uuid;
BEGIN
  FOR v_admin IN SELECT m.user_id FROM memberships m WHERE m.workspace_id = NEW.id AND m.role = 'admin' LOOP
    PERFORM recompute_scope(NEW.id, v_admin);
  END LOOP;
  RETURN NULL;
END
$$;

ALTER FUNCTION recompute_scope(uuid, uuid) OWNER TO scope_maintainer;
ALTER FUNCTION scope_touch_user() OWNER TO scope_maintainer;
ALTER FUNCTION scope_touch_workspace() OWNER TO scope_maintainer;

CREATE TRIGGER scope_grants AFTER INSERT OR UPDATE OR DELETE ON matter_grants
  FOR EACH ROW EXECUTE FUNCTION scope_touch_user();
CREATE TRIGGER scope_walls AFTER INSERT OR UPDATE OR DELETE ON matter_walls
  FOR EACH ROW EXECUTE FUNCTION scope_touch_user();
CREATE TRIGGER scope_sessions AFTER INSERT OR UPDATE OR DELETE ON access_sessions
  FOR EACH ROW EXECUTE FUNCTION scope_touch_user();
CREATE TRIGGER scope_workspace_flags AFTER UPDATE OF admin_can_read_private ON workspaces
  FOR EACH ROW EXECUTE FUNCTION scope_touch_workspace();

-- ---------------------------------------------------------------- audit immutability (doc 13.3)
CREATE FUNCTION audit_reject_change() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  RAISE EXCEPTION 'audit tables are insert-only' USING ERRCODE = '42501';
END
$$;
CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION audit_reject_change();
CREATE TRIGGER audit_payload_immutable BEFORE UPDATE OR DELETE ON audit_payload
  FOR EACH ROW EXECUTE FUNCTION audit_reject_change();
CREATE TRIGGER audit_anchor_immutable BEFORE UPDATE OR DELETE ON audit_anchor
  FOR EACH ROW EXECUTE FUNCTION audit_reject_change();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_event
  FOR EACH STATEMENT EXECUTE FUNCTION audit_reject_change();
CREATE TRIGGER audit_payload_no_truncate BEFORE TRUNCATE ON audit_payload
  FOR EACH STATEMENT EXECUTE FUNCTION audit_reject_change();
