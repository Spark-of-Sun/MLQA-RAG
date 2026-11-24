# ADR 0001: Service split

- Status: Accepted, MVP deviation in force (date 2026-11-22)
- Blueprint: sections 4.1, 4.2, 4.7; principle 4 (section 3.1); gates G0.5, G0.11, G5.2

## Context

The system holds legal and medical documents for many customers. A single process that can read documents,
call the LLM, write vectors, read audit payloads and manage accounts turns any one bug or compromise into
access to everything. The blueprint also needs the control plane (accounts, codes, approvals) to be unable to
read content, and the citation validator to be unable to call a generative model.

The split has to be enforceable by tooling, not by convention, so that a later change cannot quietly merge
two responsibilities.

## Decision

- Three planes (section 4.1): data plane (gateway data routes, ingestion, retrieval, generation, citation
  validator, audit reader), control plane (identity, gateway control routes, governance requests) and
  operations plane (ops API, operator console, KeyGuard workflow) on a separate ingress and identity provider.
- Eight backend services plus the frontend, each its own deployable with its own Docker image and
  credentials (section 4.2): `frontend` (3000), `gateway` (8000), `ingestion` (8001, plus worker, indexer, reconciler), `retrieval` (8002), `generation`
  (8003), `citation_validator` (8004), `identity` (8005), `ops` (8006), `audit` (8007).
- Each service holds only the credentials listed in the 4.2 catalog. Examples: `retrieval` has a read-only
  Qdrant key; only `ingestion` reaches the object store; only `identity` holds the Auth0 Management API
  credential; only `audit` can unwrap audit private keys.
- The Gateway orchestrates the fan-out. Services never call each other and never forward user context.
  Retrieval hands off through the retrieval ledger in PostgreSQL, so chunk text never passes through the Gateway.
- Network rules (4.7): the browser reaches only the frontend, only the frontend reaches the Gateway, only the
  Gateway reaches internal services, only `retrieval` and `ingestion` reach Qdrant.
- Code rules (4.7), enforced in CI: import-linter independence and forbidden contracts (for example the Gateway
  cannot import `lmqa_vectorstore`, `lmqa_objectstore` or decrypt functions; the validator cannot import an
  LLM client), and `ruff` TID251 bans on `sqlalchemy.create_engine` and `psycopg.connect` outside `lmqa_db`.

## Alternatives considered

- One monolith with internal modules: rejected for production because one process would hold every
  credential, so the per-service "must never" column of 4.2 could not be enforced by the platform.
- Services calling each other directly (choreography): rejected because each hop would have to forward and
  re-check user context, and chunk text would travel between services instead of being read under RLS.
- Fewer, larger services (for example retrieval and generation merged): rejected because the merged service
  would hold both the vector key and the LLM key, which 4.7 keeps apart.

## Consequences

- Positive: a compromised service exposes only what its own credentials allow; the control plane has no
  database policy on content tables; boundaries are testable.
- Positive: package boundaries are already enforced by import-linter, so the deployment split is mechanical.
- Negative: more images, roles, secrets and network policies to operate; one extra hop per call; internal
  trust needs context tokens (ADR 0008).
- Proven by G0.5 (import-linter passes and a violating control package fails), G0.11 (banned APIs), G5.2
  (only `retrieval` and `ingestion` reach Qdrant), and the per-service role checks of G1.2.

## Current state

The MVP runs the service packages inside one gateway process (deviation 1 in [docs/mvp.md](../mvp.md)). The
packages exist under `services/` (`gateway`, `identity`, `ingestion`, `retrieval`, `generation`,
`citation_validator`, `audit`); `ops` is not built (deviation 11). The import-linter contracts in
`pyproject.toml` enforce the 4.7 forbidden rules; the independence contract has one named exception for the
MVP gateway composition. Calls are in-process, without context tokens (deviation 9). The database uses one
runtime role (`lmqa_app`, `NOBYPASSRLS`) instead of one role per service.

Stage 3 closes the gap: separate deployables, per-service credentials and roles, and context tokens.
