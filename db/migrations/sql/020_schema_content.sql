-- Content-plane and audit schema (doc 11.2, 16.2, 13).

CREATE TABLE matters (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id        uuid NOT NULL REFERENCES orgs (id),
  workspace_id  uuid NOT NULL,
  label         text NOT NULL,
  type          text NOT NULL DEFAULT 'matter' CHECK (type IN ('matter', 'patient')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  UNIQUE (org_id, workspace_id, id)
);

CREATE TABLE matter_grants (
  org_id        uuid NOT NULL,
  workspace_id  uuid NOT NULL,
  matter_id     uuid NOT NULL,
  user_id       uuid NOT NULL REFERENCES users (id),
  max_tier      smallint NOT NULL CHECK (max_tier BETWEEN 1 AND 4),
  granted_by    uuid REFERENCES users (id),
  expires_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, matter_id, user_id),
  FOREIGN KEY (org_id, workspace_id, matter_id) REFERENCES matters (org_id, workspace_id, id)
);
CREATE INDEX matter_grants_user_idx ON matter_grants (workspace_id, user_id, matter_id);

-- Explicit deny for one user on one matter; beats every grant (doc 5.6).
CREATE TABLE matter_walls (
  org_id         uuid NOT NULL,
  workspace_id   uuid NOT NULL,
  matter_id      uuid NOT NULL,
  user_id        uuid NOT NULL REFERENCES users (id),
  reason_code    text NOT NULL,
  created_by     uuid REFERENCES users (id),
  effective_from timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, matter_id, user_id),
  FOREIGN KEY (org_id, workspace_id, matter_id) REFERENCES matters (org_id, workspace_id, id)
);
CREATE INDEX matter_walls_user_idx ON matter_walls (workspace_id, user_id, matter_id);

CREATE TABLE documents (
  id              uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id          uuid NOT NULL REFERENCES orgs (id),
  workspace_id    uuid NOT NULL,
  owner_user_id   uuid NOT NULL REFERENCES users (id),
  matter_id       uuid,
  title_ciphertext bytea NOT NULL,
  visibility      text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'matter')),
  confidentiality_tier smallint NOT NULL DEFAULT 1 CHECK (confidentiality_tier BETWEEN 1 AND 4),
  status          text NOT NULL DEFAULT 'uploading'
    CHECK (status IN ('uploading', 'scanning', 'parsing', 'ocr_review', 'indexing', 'indexed',
                      'failed', 'held', 'deleting', 'deleted')),
  failure_reason  text,
  current_version integer NOT NULL DEFAULT 1,
  retention_until timestamptz,
  legal_hold      boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id),
  FOREIGN KEY (org_id, workspace_id, matter_id) REFERENCES matters (org_id, workspace_id, id),
  UNIQUE (org_id, workspace_id, id),
  -- visibility 'matter' requires a matter (doc 5.4, DEF-48)
  CHECK (visibility <> 'matter' OR matter_id IS NOT NULL)
);
CREATE INDEX documents_scope_idx ON documents (workspace_id, matter_id, visibility, owner_user_id);

CREATE TABLE document_versions (
  doc_id            uuid NOT NULL,
  org_id            uuid NOT NULL,
  workspace_id      uuid NOT NULL,
  version           integer NOT NULL,
  text_source       text NOT NULL DEFAULT 'extracted'
    CHECK (text_source IN ('extracted', 'ocr', 'human_corrected')),
  index_state       text NOT NULL DEFAULT 'stale' CHECK (index_state IN ('in_sync', 'stale', 'reindexing')),
  object_key        text,
  object_sha256     text,
  embedding_version text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (doc_id, version),
  FOREIGN KEY (org_id, workspace_id, doc_id) REFERENCES documents (org_id, workspace_id, id)
);

CREATE TABLE doc_keys (
  doc_id        uuid PRIMARY KEY,
  org_id        uuid NOT NULL,
  workspace_id  uuid NOT NULL,
  wrapped_key   bytea,                     -- NULL after crypto-erase (doc 12.9)
  key_version   integer NOT NULL,          -- workspace key version that wrapped it
  state         text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'destroyed')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id, doc_id) REFERENCES documents (org_id, workspace_id, id)
);

-- Chunks are immutable per document version (doc 11.2); only access fields, is_current and
-- payload_version may change (a trigger in 040_triggers.sql enforces it).
CREATE TABLE chunks (
  id                   uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id               uuid NOT NULL,
  workspace_id         uuid NOT NULL,
  doc_id               uuid NOT NULL,
  doc_version          integer NOT NULL,
  ordinal              integer NOT NULL,
  owner_user_id        uuid NOT NULL,
  matter_id            uuid,
  visibility           text NOT NULL CHECK (visibility IN ('private', 'matter')),
  confidentiality_tier smallint NOT NULL CHECK (confidentiality_tier BETWEEN 1 AND 4),
  privilege            text NOT NULL DEFAULT 'none' CHECK (privilege IN ('none', 'attorney_client', 'work_product')),
  contains_phi         boolean NOT NULL DEFAULT false,
  kind                 text NOT NULL CHECK (kind IN (
    'preamble', 'clause', 'section', 'soap_subjective', 'soap_objective', 'soap_assessment',
    'soap_plan', 'paragraph', 'table', 'footnote')),
  section_path         text,
  clause_no            text,
  heading              text,
  page_start           integer NOT NULL,
  page_end             integer NOT NULL,
  spans                jsonb NOT NULL DEFAULT '[]'::jsonb,
  text_ciphertext      bytea NOT NULL,
  text_sha256          text NOT NULL,
  token_count          integer NOT NULL CHECK (token_count > 0),
  ocr_confidence_min   real,
  ocr_confidence_mean  real,
  quarantined          boolean NOT NULL DEFAULT false,
  text_source          text NOT NULL DEFAULT 'extracted',
  effective_date       date,
  is_current           boolean NOT NULL DEFAULT true,
  payload_version      integer NOT NULL DEFAULT 1,
  created_at           timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id, doc_id) REFERENCES documents (org_id, workspace_id, id),
  FOREIGN KEY (org_id, workspace_id, matter_id) REFERENCES matters (org_id, workspace_id, id),
  UNIQUE (doc_id, doc_version, ordinal),
  CHECK (page_end >= page_start),
  CHECK (visibility <> 'matter' OR matter_id IS NOT NULL)
);
CREATE INDEX chunks_scope_idx ON chunks (workspace_id, matter_id, visibility, owner_user_id);

-- The retrieval ledger (doc 9.4): insert-only for retrieval, select-only for generation/validator.
CREATE TABLE retrieval_records (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id        uuid NOT NULL,
  workspace_id  uuid NOT NULL,
  request_id    uuid NOT NULL UNIQUE,
  user_id       uuid NOT NULL REFERENCES users (id),
  scope_hash    text NOT NULL,
  items         jsonb NOT NULL,            -- chunk id, version, sha256, alias, rank, scores, dropped reason
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);

CREATE TABLE index_outbox (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id        uuid NOT NULL,
  workspace_id  uuid NOT NULL,
  doc_id        uuid NOT NULL,
  doc_version   integer NOT NULL,
  operation     text NOT NULL CHECK (operation IN ('upsert', 'set_payload', 'delete')),
  attempts      integer NOT NULL DEFAULT 0,
  state         text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'done', 'dead')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);
CREATE INDEX index_outbox_pending_idx ON index_outbox (state, created_at);

CREATE TABLE idempotency_keys (
  key              text NOT NULL,
  user_id          uuid NOT NULL,
  request_hash     text NOT NULL,
  response_ref     text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (key, user_id)
);

CREATE TABLE deletion_tombstones (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  scope        text NOT NULL CHECK (scope IN ('document', 'workspace', 'organization', 'tenant')),
  target_id    uuid NOT NULL,
  org_id       uuid NOT NULL,
  deleted_at   timestamptz NOT NULL DEFAULT now(),
  approver_refs jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- ------------------------------------------------------------------ audit (doc 13)
-- audit_event holds metadata only (IDs, never content); audit_payload holds the sealed content.
CREATE TABLE audit_event (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  chain_id     text NOT NULL,             -- 'ws:<workspace_id>' or 'org:<org_id>'
  seq          bigint NOT NULL,
  org_id       uuid NOT NULL,
  workspace_id uuid,
  ts           timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor_id     uuid,
  actor_role   text,
  action       text NOT NULL,
  target       text,
  outcome      text NOT NULL,
  reason_code  text,
  request_id   uuid,
  ip           inet,
  user_agent   text,
  scope        text NOT NULL CHECK (scope IN ('org', 'admin', 'workspace', 'tenant')),
  prev_hash    bytea NOT NULL,
  payload_hash bytea,
  hash         bytea NOT NULL,
  UNIQUE (chain_id, seq)
);
CREATE INDEX audit_event_ws_idx ON audit_event (workspace_id, ts);
CREATE INDEX audit_event_actor_idx ON audit_event (workspace_id, actor_id, ts);

CREATE TABLE audit_payload (
  event_id     uuid PRIMARY KEY REFERENCES audit_event (id),
  org_id       uuid NOT NULL,
  workspace_id uuid,
  ciphertext   bytea NOT NULL,            -- HPKE-sealed to the workspace-month public key (doc 13.2)
  key_id       text NOT NULL
);

CREATE TABLE audit_keys (
  id                  uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id              uuid NOT NULL REFERENCES orgs (id),
  workspace_id        uuid NOT NULL,
  month               date NOT NULL,
  public_key          bytea NOT NULL,
  wrapped_private_key bytea,              -- NULL once the month's key is destroyed
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, month),
  FOREIGN KEY (org_id, workspace_id) REFERENCES workspaces (org_id, id)
);

CREATE TABLE audit_anchor (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  ts          timestamptz NOT NULL DEFAULT now(),
  merkle_root bytea NOT NULL,
  heads       jsonb NOT NULL,
  object_key  text
);
