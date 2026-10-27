-- 001_initial_schema.sql
-- Multi-tenant schema per Master System Design §16.2 with strict FORCE ROW LEVEL SECURITY

-- 1. Organizations
CREATE TABLE IF NOT EXISTS orgs (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Workspaces
CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Documents
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploading',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. Document Chunks
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INT NOT NULL,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_doc_chunk_ordinal UNIQUE (doc_id, ordinal)
);

-- 5. Audit Events (Append-Only)
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    sequence_num BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_audit_seq UNIQUE (workspace_id, sequence_num)
);

-- Row-Level Security: Enable and FORCE on all tables
ALTER TABLE orgs ENABLE ROW LEVEL SECURITY;
ALTER TABLE orgs FORCE ROW LEVEL SECURITY;

ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces FORCE ROW LEVEL SECURITY;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

-- Tenant Isolation Policies binding to lmqa.current_tenant_id session variable
DROP POLICY IF EXISTS tenant_isolation_orgs ON orgs;
CREATE POLICY tenant_isolation_orgs ON orgs
    FOR ALL
    USING (id = NULLIF(current_setting('lmqa.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation_workspaces ON workspaces;
CREATE POLICY tenant_isolation_workspaces ON workspaces
    FOR ALL
    USING (org_id = NULLIF(current_setting('lmqa.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation_documents ON documents;
CREATE POLICY tenant_isolation_documents ON documents
    FOR ALL
    USING (org_id = NULLIF(current_setting('lmqa.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation_document_chunks ON document_chunks;
CREATE POLICY tenant_isolation_document_chunks ON document_chunks
    FOR ALL
    USING (org_id = NULLIF(current_setting('lmqa.current_tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation_audit_events ON audit_events;
CREATE POLICY tenant_isolation_audit_events ON audit_events
    FOR ALL
    USING (org_id = NULLIF(current_setting('lmqa.current_tenant_id', true), '')::uuid);
