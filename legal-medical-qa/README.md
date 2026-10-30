# Onekami: citation-verified answers over legal and medical documents

Ask a question in plain language and get an answer in which **every sentence carries a machine-verified
citation** (document, page, clause, highlighted span), or a refusal when the documents do not support one.
Multi-tenant for law firms and hospital systems; audit-logged end to end.

> **Status: working MVP, not yet verified live.** The data layer, security libraries, all seven services, the
> frontend and the infrastructure code exist and pass their model-free tests against real servers. Nothing has
> yet run against a real Auth0 tenant, real AWS, an LLM, or the ML models in the sandbox this was built in.
> **Read [`docs/STATUS.md`](docs/STATUS.md) before relying on any guarantee.** Every guarantee is a design claim
> until the gate that proves it passes.

## How it fits together

```
browser -> Cloudflare (DNS, WAF, TLS) -> AWS load balancer -> frontend (Next.js 16, BFF, holds the tokens)
                                                                    |
                                                                 gateway  (token check, principal, allow-list, gated release)
              +-----------+------------+-------------+-------------+--------------+
           identity   ingestion     retrieval    generation   citation_validator   audit
              |           |             |             |              |               |
          PostgreSQL 18 (row-level security = the final authority) . Valkey . Qdrant . S3 . KMS
```

* **Auth0 authenticates; PostgreSQL authorizes.** Roles, workspaces, grants, ethical walls and approvals live in the
  database and are resolved on every request, so suspension takes effect in seconds.
* **The database is the final authority, not the vector store.** Qdrant narrows search; PostgreSQL decides what a
  caller may read, and every returned ID is cross-checked.
* **No unverified text reaches a user.** The validator checks every sentence (tags, ledger, content hash, numbers and
  dates, entailment) and signs a verdict; the gateway releases a sentence only with a valid verdict and a committed audit record.

## Repository map

| Path | What it is |
| --- | --- |
| `services/` | `gateway`, `identity`, `ingestion`, `retrieval`, `generation`, `citation_validator`, `audit` (FastAPI) |
| `libs/` | `lmqa_db` (scoped sessions), `lmqa_keys` (envelope encryption, KMS), `lmqa_auth`, `lmqa_security`, `lmqa_vectorstore`, `lmqa_objectstore`, `lmqa_audit`, `lmqa_models`, `lmqa_testing` |
| `db/` | Alembic migrations, row-level security policies, roles and grants |
| `frontend/` | Next.js 16 application (proxy, BFF, pages) |
| `contracts/` | authorization matrix, state machines, feature flags, exported OpenAPI |
| `infra/` | `aws/`, `cloudflare/`, `auth0/` (OpenTofu), `k8s/`, `compose/`, `docker/`, `keyguard/` |
| `corpus/` | fetcher and manifest for the real public documents used by tests |
| `tools/` | `db_migrate`, `gen_env`, `doctor`, `gatekeeper`, `gen_k8s`, `export_openapi` |
| `docs/` | `STATUS.md`, `architecture.md`, `versions.md`, `deployment-onekami.md`, `adr/`, `runbooks/` |

## Run it locally

```bash
make sync                         # uv sync --frozen --all-packages  (Python 3.14)
make env FORCE=1                  # fill .env with strong random LOCAL secrets (third-party keys stay <PLACEHOLDERS>)
make infra-test                   # PostgreSQL, PgBouncer, Valkey, OpenBao, Qdrant, SeaweedFS in Docker
make migrate                      # roles, database, migrations
make load-corpus                  # fetch the real public documents the tests use (not shipped in the zip)
make test                         # every test that needs no ML model and no AWS credentials
make lint                         # ruff + pyright + import boundaries
make doctor                       # what is configured, what is missing, what is reachable
```

`.env` ships with **placeholders only** for every API key and secret. You provide: Auth0 (domain, client IDs and
secrets), an LLM key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`), AWS credentials (or an assumed role), the Cloudflare
API token and zone, SMTP. `make doctor` lists exactly which are still missing.

## Deploy to onekami.site

Follow [`docs/deployment-onekami.md`](docs/deployment-onekami.md): Cloudflare in front, everything else on AWS
(OpenTofu for `infra/aws`, `infra/cloudflare`, `infra/auth0`; Kubernetes manifests in `infra/k8s`).

## Tests that need a bigger machine

Tests that load an ML model are marked `live_models`, real-KMS tests `live_aws`. They were **not run** where this was
built (2 GB of RAM). Run them on a machine with at least 8 GB: `make test-models`, `make test-aws`.
