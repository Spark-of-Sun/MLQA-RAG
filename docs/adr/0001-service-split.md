# ADR 0001: Split into five independently deployable services

- **Status:** Accepted
- **Date:** 2026-10-14

## Context

The system ingests large legal/medical documents, retrieves relevant
chunks, generates a cited answer with an LLM, and validates every citation
before the answer reaches the user. These four stages, plus the API/auth
boundary, have very different resource profiles and failure modes:

- **Ingestion** is bursty and CPU/IO-heavy (OCR, embedding) — a burst of
  uploads should not slow down live queries.
- **Retrieval** is latency-sensitive and benefits from GPU-backed
  re-rankers.
- **Generation** is the single most expensive per-call resource (LLM
  tokens) and is the natural point for blue/green or canary rollout when a
  prompt template changes.
- **Citation validation** is deterministic and non-LLM — it must never be
  skipped, and it should never share a failure domain with the LLM call it
  is checking.
- **Gateway** is the only service the browser ever talks to, and owns
  auth, rate limiting, and tenant/matter/patient scoping.

A single monolith would couple the scaling policy, deploy cadence, and
blast radius of all five concerns together.

## Decision

Build five independently deployable services — `gateway`, `ingestion`,
`retrieval`, `generation`, `citation_validator` — each with its own
Dockerfile, its own test suite, and (in production) its own Kubernetes
deployment and HPA policy. All five, plus the frontend, share request/data
contracts defined once in `libs/common/models` and `docs/api-contracts/`,
so no service can drift from the agreed shape.

The ingestion worker pool (Celery/Arq) is split from the ingestion API
process (`Dockerfile.worker` vs `Dockerfile`) for the same reason: upload
intake must stay responsive even while OCR/embedding jobs queue up behind
it.

Locally, every service still runs as its own container via
`docker-compose.yml`, with the same service boundaries as production — the
only difference is the infra each depends on (local Postgres/Qdrant/MinIO
vs managed equivalents), controlled entirely through `.env`.

## Consequences

**Positive**
- Each service scales on its own metric (gateway on request rate;
  retrieval/generation on GPU or queue depth; ingestion on worker queue
  depth) instead of one shared policy for everything.
- Citation validation can never be bypassed by a code path inside
  generation, because it is a separate process the gateway must call.
- A prompt-template or model change only needs a canary rollout of
  `generation`; `citation_validator`'s pass-rate metric is the automatic
  gate for that rollout.
- Local dev and production use the identical topology, so "works locally"
  claims actually transfer.

**Negative / trade-offs**
- More moving parts locally: five FastAPI processes instead of one. Offset
  by `docker-compose.yml` + `make up` bringing up the whole stack in one
  command.
- Inter-service calls add network hops and require a shared auth
  mechanism (internal API key locally, mTLS/signed service tokens in
  production) rather than in-process function calls.
- Shared contracts (`libs/common/models`, `docs/api-contracts/`) must be
  versioned carefully — a breaking change to the `Chunk` or `Citation`
  schema touches every service.

## Alternatives considered

- **Single monolith FastAPI app:** simplest to run locally, but couples
  ingestion's bursty load to retrieval's latency SLOs, and makes it
  impossible to canary a generation/prompt change without redeploying
  everything, including the citation validator it's supposed to be
  checked by.
- **Three services (merge retrieval+generation, keep validator
  separate):** rejected because retrieval and generation have different
  scaling drivers (latency vs GPU-token cost) and different deploy
  cadences (retrieval changes rarely; generation/prompt changes often).
