# System Architecture: Legal & Medical Q&A (M1 / M1a)
# Reference: Master System Design v3.1 & MVP Prototype Report v1.0

## Overview

The system is a multi-tenant legal and medical document question-answering platform providing high-assurance sentence-gated answers backed by verified source citations.

Current Release Target: **M1a** (first working cut), Profile: `mvp-a`.
- Legal documents only (medical domain deferred per DR-14)
- Object storage configured with Azure Blob Storage per .env.example reference
- OCR quarantine flow deferred (DR-15)
- Three critical alerts active (DR-17)
- 100 live queries (DR-18)
- 1 passing acceptance run (DR-19)

## Architecture Principles & Non-Negotiables

1. **PostgreSQL Row-Level Security (RLS)** is the ultimate data isolation barrier.
2. **Key Hierarchy**: Envelope encryption with tenant-level and document-level keys managed via Azure Key Vault / OpenBao.
3. **Sentence-Gated Release**: Answers pass through `citation_validator` with strict NLI entailment before any sentence is displayed to users.
4. **Append-Only Audit**: Cryptographically hash-chained audit trail with periodic external anchors.
5. **Real Systems Only**: No mocks or fake data in test or execution paths. Negative controls are labeled instruments.
6. **Strict Import Boundaries**: Verified by `import-linter` (Master §4.7).

## Component Map

- **`frontend/`**: Next.js 16 UI with BFF architecture
- **`services/gateway/`**: Ingress API, JWT validation, context token issuance
- **`services/identity/`**: Onboarding, tenant management, organization lifecycle
- **`services/ingestion/`**: Document scanning, chunking, embedding, indexing
- **`services/retrieval/`**: Vector similarity search + lexical retrieval + re-ranking
- **`services/generation/`**: Grounded answer synthesis
- **`services/citation_validator/`**: NLI sentence-level claim verification
- **`services/audit/`**: Audit chain verification and anchoring
- **`services/ops/`**: Operator plane and health monitoring
