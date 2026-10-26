# 0001. Service Boundaries and Reserved Ports

- **Status:** Accepted
- **Deciders:** Maya Okafor (Tech Lead), Coordinator
- **Date:** 2026-10-26

## Context

Per Master System Design §4.2, the LMQA system splits functionality into 8 microservices and a Next.js 16 frontend to enforce strict failure boundaries, least-privilege key access, and independent deployments.

## Decision

We adopt the single-responsibility service topology with reserved internal ports:

| Service | Port | Primary Boundary |
|---|---|---|
| `frontend` | 3000 | Next.js 16 UI and BFF |
| `gateway` | 8000 | Authentication, perimeter route allow-list, context tokens |
| `ingestion` | 8001 | Document scanning, parsing, chunking, S3 upload |
| `retrieval` | 8002 | Hybrid vector + lexical search, re-ranking |
| `generation` | 8003 | LLM prompt synthesis, token budget management |
| `citation_validator` | 8004 | Sentence-level claim verification via NLI |
| `identity` | 8005 | Onboarding, organization lifecycle, membership |
| `ops` | 8006 | Platform operator console, JIT access, health checks |
| `audit` | 8007 | Sealed audit log verification and external anchoring |

## Consequences

- No service may directly import or call another service; all service-to-service communication uses scoped HTTP/REST with context tokens.
- Import boundary enforcement is strictly checked in CI via `import-linter`.
