-- Request context and the access-decision helper (doc 10.3, 5.4).
--
-- Context is set per TRANSACTION with set_config(name, value, true): safe under PgBouncer
-- transaction pooling (session-level settings would leak between requests).
--
-- FAIL CLOSED (DEF-52): after any earlier transaction-local set_config on a pooled connection,
-- current_setting(name, true) returns '' (empty string), not NULL, and casting '' to uuid
-- raises an error instead of matching nothing. NULLIF turns '' into NULL, and NULL matches no row.

CREATE FUNCTION app_org() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$;

CREATE FUNCTION app_ws() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid $$;

CREATE FUNCTION app_user() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.role', true), '') $$;

-- True when the context role is the identity service acting for the platform (provisioning).
CREATE FUNCTION app_is_system() RETURNS boolean LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT coalesce(app_role() = 'system', false) $$;

-- Rule 1 of doc 5.4: the membership, the workspace and the organization must all be active.
CREATE FUNCTION app_actor_active() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$
  SELECT coalesce((
    SELECT m.state = 'active' AND w.state = 'active' AND o.state = 'active'
      FROM memberships m
      JOIN workspaces w ON w.id = m.workspace_id AND w.org_id = m.org_id
      JOIN orgs o ON o.id = m.org_id
     WHERE m.user_id = app_user()
       AND m.org_id = app_org()
       AND m.workspace_id = app_ws()
  ), false)
$$;

-- The complete document access decision (doc 5.4), in the exact rule order. A rule earlier in
-- the order wins. The Python oracle lmqa_models.access.decide implements the same function and
-- the differential test (G1.4) proves they agree.
CREATE FUNCTION app_can_access(
  p_owner uuid, p_matter uuid, p_visibility text, p_tier integer
) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$
DECLARE
  v_user uuid := app_user();
  v_ws   uuid := app_ws();
  v_role text := app_role();
BEGIN
  IF v_user IS NULL OR v_ws IS NULL OR v_role IS NULL THEN
    RETURN false;
  END IF;
  -- Super Admins and operators never reach the content decision (doc 5.4).
  IF v_role NOT IN ('admin', 'tenant') THEN
    RETURN false;
  END IF;
  -- Rule 1: membership, workspace and organization must be active.
  IF NOT app_actor_active() THEN
    RETURN false;
  END IF;
  -- Rule 2: a wall beats everything below (grants, ownership, admin, emergency, break-glass).
  IF p_matter IS NOT NULL AND EXISTS (
    SELECT 1 FROM matter_walls w
     WHERE w.workspace_id = v_ws AND w.user_id = v_user AND w.matter_id = p_matter
  ) THEN
    RETURN false;
  END IF;
  -- Rule 3: the owner reads their own document.
  IF p_owner = v_user THEN
    RETURN true;
  END IF;
  -- Rule 4: an admin reads matter-shared documents at every tier.
  IF v_role = 'admin' AND p_visibility = 'matter' THEN
    RETURN true;
  END IF;
  -- Rule 5: a tenant with an unexpired grant whose ceiling covers the tier.
  IF v_role = 'tenant' AND p_visibility = 'matter' AND p_matter IS NOT NULL AND EXISTS (
    SELECT 1 FROM matter_grants g
     WHERE g.workspace_id = v_ws AND g.user_id = v_user AND g.matter_id = p_matter
       AND g.max_tier >= p_tier AND (g.expires_at IS NULL OR g.expires_at > now())
  ) THEN
    RETURN true;
  END IF;
  -- Rule 6: active clinical emergency exception, tier capped at 3 (tier 4 never).
  IF v_role = 'tenant' AND p_visibility = 'matter' AND p_matter IS NOT NULL AND p_tier <= 3 AND EXISTS (
    SELECT 1 FROM access_sessions s
     WHERE s.workspace_id = v_ws AND s.user_id = v_user AND s.kind = 'emergency'
       AND s.state = 'active' AND s.matter_id = p_matter AND s.expires_at > now()
  ) THEN
    RETURN true;
  END IF;
  -- Rule 7: admin, private document, the workspace flag AND an active break-glass session.
  IF v_role = 'admin' AND p_visibility = 'private' AND EXISTS (
    SELECT 1 FROM workspaces w WHERE w.id = v_ws AND w.admin_can_read_private
  ) AND EXISTS (
    SELECT 1 FROM access_sessions s
     WHERE s.workspace_id = v_ws AND s.user_id = v_user AND s.kind = 'break_glass'
       AND s.state = 'active' AND s.expires_at > now()
  ) THEN
    RETURN true;
  END IF;
  -- Rule 8: anything else is denied.
  RETURN false;
END
$$;
