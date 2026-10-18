# Legal/Medical Document Q&A System

Cited-RAG question answering over large legal and medical document sets
(contracts, case files, clinical notes, regulatory filings), with
machine-validated, page/clause-level citations on every answer.

This repo runs the **full production service topology on a single machine**
via `docker compose`. Every managed/cloud dependency (S3, managed Postgres,
managed vector DB, Okta/Azure AD, Kubernetes) has a drop-in local substitute,
so the service boundaries are identical between local dev and production —
swapping to cloud later is a config change, not a rewrite.

See `docs/architecture.md` for the full design doc.

## Services

| Service            | Responsibility                                               | Local port |
|---------------------|---------------------------------------------------------------|------------|
| `gateway`            | Auth, rate limiting, request validation, routing. Only service the frontend calls. | 8000 |
| `ingestion`          | Upload intake, OCR, chunking, embedding (async background jobs). | 8001 (+ worker pool) |
| `retrieval`          | Hybrid search, metadata filtering, cross-encoder re-ranking.  | 8002 |
| `generation`         | Token budget, compression, prompt assembly, LLM call.         | 8003 |
| `citation_validator` | Deterministic, non-LLM, post-generation citation gate.         | 8004 |
| `frontend`           | Next.js 14+ App Router UI.                                     | 3000 |

Infra: Postgres (metadata/RBAC + audit log), Redis (semantic cache, sessions,
rate limiting), Qdrant (vector DB), MinIO (S3-compatible object storage).

## Prerequisites

- Docker + Docker Compose v2
- `make`
- A real LLM provider API key (no self-hosted model required for local
  testing — see `.env.example`)

## Quick start

```bash
cp .env.example .env
# edit .env: at minimum set LLM_API_KEY

make up      # builds and starts the full local stack
make seed    # loads a demo tenant + sample legal/medical documents
make eval    # runs the citation-validation eval set against the live stack
```

Then open the frontend at http://localhost:3000. The frontend talks only to
the Gateway at http://localhost:8000.

## Common commands

```bash
make up        # start the full stack (detached)
make down      # stop the stack
make logs      # tail logs for all services
make seed      # (re-)load demo tenant/data
make eval      # run prompts/eval_sets against the live stack
make test      # run unit tests for every service
make test-e2e  # run full query-to-cited-answer flow against the local stack
```

## Repository layout

```
legal-medical-qa/
├── docs/            # architecture, ADRs, OpenAPI contracts, runbooks
├── frontend/        # Next.js 14+ App Router UI
├── services/        # gateway, ingestion, retrieval, generation, citation_validator
├── libs/            # shared Python packages (common models, auth, security, telemetry)
├── prompts/         # versioned prompt templates, few-shot examples, eval sets
├── db/              # Alembic migrations + seed scripts
├── infra/           # local infra config, k8s manifests, terraform
├── scripts/         # bootstrap / seed / eval scripts
├── tests/           # e2e + load tests
└── .github/         # CI workflows
```

## Build order

This repo is built in the milestone order in `docs/architecture.md` §9:
scaffold + contracts → ingestion → retrieval → generation (uncited) →
citation validator (hard gate) → frontend → audit/RBAC → eval harness →
production infra (`infra/k8s`, `infra/terraform`).

## Security & compliance notes

- Row-level security (tenant/matter/patient) is enforced in Postgres from
  the first migration, not bolted on later.
- PHI/privileged fields are column-level encrypted even in local/demo mode.
- The audit log is append-only (insert-only DB grants locally; WORM storage
  in production) and is written to by every service on every request.

This system does **not** provide legal or medical advice. It surfaces and
cites what the source documents say; disclaimers and human-review workflows
are part of the product surface.