-- 001_service_roles.sql
-- Service-scoped least-privilege roles matching .env.example and Master System Design §16.3

DO $$
BEGIN
    -- 1. Gateway
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_gateway') THEN
        CREATE ROLE lmqa_gateway WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 2. Identity
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_identity') THEN
        CREATE ROLE lmqa_identity WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 3. Ingestion
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_ingestion') THEN
        CREATE ROLE lmqa_ingestion WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 4. Retrieval
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_retrieval') THEN
        CREATE ROLE lmqa_retrieval WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 5. Generation
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_generation') THEN
        CREATE ROLE lmqa_generation WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 6. Validator
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_validator') THEN
        CREATE ROLE lmqa_validator WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 7. Audit
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_audit') THEN
        CREATE ROLE lmqa_audit WITH LOGIN PASSWORD 'secret';
    END IF;

    -- 8. Ops
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'lmqa_ops') THEN
        CREATE ROLE lmqa_ops WITH LOGIN PASSWORD 'secret';
    END IF;
END $$;

-- Schema usage
GRANT USAGE ON SCHEMA public TO
    lmqa_gateway,
    lmqa_identity,
    lmqa_ingestion,
    lmqa_retrieval,
    lmqa_generation,
    lmqa_validator,
    lmqa_audit,
    lmqa_ops;

-- Table permissions (Least Privilege)
-- Identity owns tenant onboarding and workspace creation
GRANT SELECT, INSERT, UPDATE ON orgs, workspaces TO lmqa_identity;

-- Ingestion owns document processing and chunking
GRANT SELECT, INSERT, UPDATE ON documents, document_chunks TO lmqa_ingestion;

-- Retrieval, Generation, and Validator need to read chunks under RLS
GRANT SELECT ON documents, document_chunks TO lmqa_retrieval;
GRANT SELECT ON document_chunks TO lmqa_generation;
GRANT SELECT ON document_chunks TO lmqa_validator;

-- Audit service appends and verifies audit events
GRANT SELECT, INSERT ON audit_events TO lmqa_audit;

-- Ops service checks table health and metrics
GRANT SELECT ON orgs, workspaces, documents TO lmqa_ops;
