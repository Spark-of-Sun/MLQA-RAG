-- Control-plane schema (doc 16.2). UUIDv7 keys (PostgreSQL 18 uuidv7()), timestamptz everywhere.
-- Foreign keys are composite so a row cannot point into another workspace (doc 5.1, G1.6).
-- Status columns are text + CHECK; transitions are enforced by generated triggers (doc 6.1).

-- No function ever gets PUBLIC execute by default: every EXECUTE is an explicit grant (G1.2).
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE orgs (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  auth0_org_id    text UNIQUE,
  name            text NOT NULL,
  deployment_type text NOT NULL CHECK (deployment_type IN ('legal', 'medical', 'both')),
  region          text NOT NULL DEFAULT 'us',
  state           text NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending', 'active', 'frozen', 'deletion_pending', 'sealed', 'destroyed', 'rejected')),
  retention_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  legal_hold      boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  auth0_sub           text NOT NULL UNIQUE,
  email_ciphertext    bytea,
  email_blind_index   bytea UNIQUE,
  auth_strength_last  text,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
  id                      uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id                  uuid NOT NULL REFERENCES orgs (id),
  admin_user_id           uuid REFERENCES users (id),
  state                   text NOT NULL DEFAULT 'pending'
    CHECK (state IN ('pending', 'provisioning', 'active', 'frozen', 'sealed', 'destroyed', 'rejected')),
  admin_can_read_private  boolean NOT NULL DEFAULT false,
  emergency_access        boolean NOT NULL DEFAULT false,
  join_policy             text NOT NULL DEFAULT 'manual'
    CHECK (join_policy IN ('manual', 'domain_allowlist', 'auto')),
  default_visibility      text NOT NULL DEFAULT 'private' CHECK (default_visibility IN ('private', 'matter')),
  delivery_mode           text NOT NULL DEFAULT 'sentence_gated'
    CHECK (delivery_mode IN ('sentence_gated', 'buffered')),
  on_fail                 text NOT NULL DEFAULT 'strip' CHECK (on_fail IN ('strip', 'regenerate', 'refuse')),
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (org_id, id),
  -- regenerate requires buffered delivery (doc 11.6)
  CHECK (on_fail <> 'regenerate' OR delivery_mode = 'buffered')
);

CREATE TABLE memberships (
  id                uuid PRIMARY KEY DEFAULT uuidv7(),
  user_id           uuid NOT NULL UNIQUE REFERENCES users (id),  -- one membership per user in v1 (D7)
  org_id            uuid NOT NULL REFERENCES orgs (id),
  workspace_id      uuid,
  role              text NOT NULL CHECK (role IN ('super_admin', 'admin', 'tenant')),
  state             text NOT NULL DEFAULT 'pending_approval'
    CHECK (state IN ('pending_approval', 'active', 'suspended', 'rejected', 'removed')),
  state_reason      text,
  principal_version integer NOT NULL DEFAULT 1,
  scope_version     integer NOT NULL DEFAULT 1,
  scope_hash        text NOT NULL DEFAULT '',
  approved_by       uuid REFERENCES users (id),
  owner_linked      boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  CHECK (role = 'super_admin' OR workspace_id IS NOT NULL),
  -- nobody approves their own membership (doc 6.2)
  CHECK (approved_by IS DISTINCT FROM user_id)
);
CREATE INDEX memberships_ws_idx ON memberships (workspace_id, role, state);

CREATE TABLE join_codes (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  kind          text NOT NULL CHECK (kind IN ('org', 'admin', 'successor')),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  workspace_id  uuid,
  lookup_id     text NOT NULL UNIQUE,
  code_hash     bytea NOT NULL,          -- keyed HMAC-SHA-256, never the code itself (doc 7.6)
  pepper_id     text NOT NULL,
  expires_at    timestamptz NOT NULL,
  max_uses      integer NOT NULL CHECK (max_uses > 0),
  used_count    integer NOT NULL DEFAULT 0 CHECK (used_count >= 0),
  bound_email_index bytea,
  state         text NOT NULL DEFAULT 'active'
    CHECK (state IN ('active', 'rotated', 'expired', 'exhausted', 'disabled', 'revoked')),
  created_by    uuid REFERENCES users (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  -- Organization Codes bind to the org; Admin Codes and successor invites bind to a workspace.
  CHECK ((kind = 'org') = (workspace_id IS NULL)),
  CHECK (used_count <= max_uses)
);

CREATE TABLE join_attempts (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  lookup_id    text,
  user_id      uuid,
  ip           inet,
  outcome      text NOT NULL,
  true_reason  text,                      -- the real failure reason; users only ever see a uniform error
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX join_attempts_user_idx ON join_attempts (user_id, created_at);
CREATE INDEX join_attempts_ip_idx ON join_attempts (ip, created_at);

CREATE TABLE governance_requests (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  workspace_id  uuid,
  kind          text NOT NULL CHECK (kind IN (
    'successor_transfer', 'private_read_enable', 'wall_lift', 'workspace_unseal',
    'workspace_destroy', 'org_delete', 'owner_recovery', 'co_owner_set')),
  target_id     uuid,
  initiator_id  uuid NOT NULL REFERENCES users (id),
  state         text NOT NULL DEFAULT 'requested'
    CHECK (state IN ('requested', 'approved', 'waiting', 'executable', 'executed',
                     'rejected', 'cancelled', 'expired', 'failed')),
  wait_until    timestamptz,
  expires_at    timestamptz NOT NULL,
  reason_code   text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);

CREATE TABLE governance_approvals (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  request_id    uuid NOT NULL REFERENCES governance_requests (id),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  approver_id   uuid NOT NULL REFERENCES users (id),
  approved_at   timestamptz NOT NULL DEFAULT now(),
  auth_proof_ref text,
  UNIQUE (request_id, approver_id)        -- one human cannot approve twice (G2.10)
);

-- Break-glass, clinical emergency and operator JIT share one lifecycle (doc 6.8).
CREATE TABLE access_sessions (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  workspace_id  uuid NOT NULL,
  user_id       uuid NOT NULL REFERENCES users (id),   -- the person the session is for
  kind          text NOT NULL CHECK (kind IN ('break_glass', 'emergency', 'operator_jit')),
  matter_id     uuid,
  state         text NOT NULL DEFAULT 'requested'
    CHECK (state IN ('requested', 'approved', 'denied', 'active', 'expired', 'revoked', 'reviewed')),
  reason_code   text NOT NULL,
  expires_at    timestamptz NOT NULL,
  approved_by   uuid REFERENCES users (id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  CHECK (kind <> 'emergency' OR matter_id IS NOT NULL)
);
CREATE INDEX access_sessions_lookup_idx ON access_sessions (workspace_id, user_id, kind, state, expires_at);

-- Numbers only; the only workspace data the super_admin role may read (doc 5.3, 16.2).
CREATE TABLE workspace_usage (
  workspace_id    uuid PRIMARY KEY,
  org_id          uuid NOT NULL REFERENCES orgs (id),
  tenant_count    integer NOT NULL DEFAULT 0,
  document_count  integer NOT NULL DEFAULT 0,
  query_count     bigint NOT NULL DEFAULT 0,
  token_usage     bigint NOT NULL DEFAULT 0,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);

-- Key material is stored wrapped, never plaintext (doc 12.1).
CREATE TABLE org_keys (
  org_id               uuid PRIMARY KEY REFERENCES orgs (id),
  kms_key_id           text NOT NULL,
  replica_key_id       text,
  escrow_key_id        text,
  deletion_protection  boolean NOT NULL DEFAULT true,
  state                text NOT NULL DEFAULT 'active',
  created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workspace_keys (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  workspace_id  uuid NOT NULL,
  version       integer NOT NULL,
  wrapped_key   bytea,                     -- NULL once the workspace is sealed (doc 12.6)
  escrow_wrapped_key bytea,
  state         text NOT NULL DEFAULT 'active',
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, version),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);
