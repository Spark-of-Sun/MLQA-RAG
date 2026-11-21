# Version ledger

Generated 2026-10-30 by `tools/gen_versions.py` from `uv.lock` and `frontend/pnpm-lock.yaml`.
The lockfiles and the container image digests are the authority; this file is their report.

## Runtime and tools

| Tool | Version |
| --- | --- |
| Python | 3.14.10 (pinned 3.14 in `.python-version`) |
| uv | uv 0.13.6 (x86_64-unknown-linux-gnu) |
| Node.js (frontend build) | v20.20.2 (Docker image uses 24 LTS) |
| pnpm | 12.16.1 |
| OpenTofu | 1.13.2 (used to validate infra/) |

## Python packages (selected)

| Package | Locked version |
| --- | --- |
| fastapi | 0.162.0 |
| pydantic | 2.14.2 |
| sqlalchemy | 2.1.6 |
| psycopg | 3.3.6 |
| alembic | 1.20.1 |
| valkey | 6.2.0 |
| qdrant-client | 1.20.0 |
| pyjwt | 2.15.1 |
| cryptography | 50.0.2 |
| pyhpke | 0.6.5 |
| boto3 | 1.43.122 |
| httpx | 0.28.1 |
| uvicorn | 0.54.0 |
| fastembed | 0.9.1 |
| tokenizers | 0.23.3 |
| onnxruntime | 1.31.1 |
| pypdfium2 | 5.14.0 |
| lxml | 6.1.3 |
| python-docx | 1.2.0 |
| anthropic | 2.3.0 |
| openai | 3.41.0 |
| pytest | 9.2.0 |
| hypothesis | 6.170.14 |
| ruff | 0.17.3 |
| pyright | 1.1.414 |
| import-linter | 2.15 |
| websockets | 17.3 |

## Frontend packages (selected)

| Package | Locked version |
| --- | --- |
| next | 16.4.3 |
| react | 19.3.1 |
| react-dom | 19.3.1 |
| @auth0/nextjs-auth0 | 4.33.0 |
| ioredis | 6.0.0 |
| eventsource-parser | 4.1.3 |
| tailwindcss | 4.3.3 |
| typescript | 6.0.3 |
| eslint | 10.13.0 |
| vitest | 5.0.5 |

## Infrastructure servers used by the tests (real, not mocked)

| Server | Version |
| --- | --- |
| PostgreSQL | 18.6 |
| PgBouncer | 1.26.1 (built from source) |
| Valkey | 9.1.3 (built from source) |
| Qdrant | 1.20.0 |
| OpenBao | 2.7.2 |
| SeaweedFS | 4.51 |

## OpenTofu providers

| Provider | Version constraint |
| --- | --- |
| hashicorp/aws | ~> 6.71 |
| cloudflare/cloudflare | ~> 5.28 |
| auth0/auth0 | ~> 1.59 |

## Deliberate deviations from 'newest'

* **TypeScript is 6.0.x, not 7.x.** `typescript-eslint` 8.72 refuses TypeScript 7 (peer range `<6.1.0`) and `next build` uses the
  TypeScript JS API. Revisit when `typescript-eslint` supports TypeScript 7.1 or later.
* Qdrant, PostgreSQL, Valkey and the other servers above are the versions the tests ran against here; pin container images by digest before production.
