# Legal/Medical Document Q&A System — Architecture

> Mirrored in-repo for offline reference. This is the source of truth for
> service boundaries, data flow, and the build order; keep it in sync with
> any change to `docs/api-contracts/` or the service topology below.

## 1. Overview

Answers natural-language questions against large legal and medical document
sets (contracts, case files, clinical notes, regulatory filings) and returns
answers with verifiable, page/clause-level citations. Built for environments
where an unsupported or hallucinated answer is a compliance and liability
risk, not just a quality issue.

**Design goals**
- Every answer is grounded in retrieved source text; the system refuses to
  answer when grounding is insufficient.
- Every citation is machine-validated against the retrieved chunks before
  the answer reaches the user.
- Long source documents (50–200+ pages) are handled within a bounded token
  budget per query through structure-aware chunking, re-ranking, and
  compression.
- Multi-tenant, audit-logged, HIPAA- and privilege-aware.
- Retrieval and inference layers scale independently of the stateless
  API/UI layers.

**Non-goals**
The system does not provide legal or medical advice; it surfaces and cites
what the source documents say. Disclaimers and human-review workflows are
part of the product surface.

## 2. Service topology

```
Next.js UI
  -> API Gateway (FastAPI)            [only service the browser talks to]
      -> Retrieval service  -> Vector DB (Qdrant) + Postgres (metadata/RBAC)
      -> Generation service -> LLM Provider (API, swappable to local model)
      -> Citation Validator -> (deterministic, no LLM; checks Retrieval's chunk set)

Ingestion service (independent, async)
  -> OCR -> Chunker -> Embedder -> Vector DB + Object Storage

Audit/event log (append-only) <- written by every service on every request
```

**Flow per query:** Gateway authenticates + scopes by tenant/matter/patient
→ Retrieval (hybrid search + re-rank, metadata-filtered) → Generation (token
budget, compression, prompt assembly, LLM call) → Citation Validator (checks
every `[chunk_N]` tag against the actual retrieved text) → streamed,
verified answer → audit log write.

## 3. Service responsibilities

| Service | Owns | Does NOT own | Local port |
|---|---|---|---|
| Gateway | Auth, rate limiting, request validation, routing — only service the frontend calls | Any retrieval/LLM logic | 8000 |
| Ingestion | Upload intake, OCR, chunking, embedding; writes to vector + object store; async background jobs | Query-time search | 8001 (+ worker pool) |
| Retrieval | Hybrid search, metadata filtering, re-ranking | Prompt assembly, LLM calls | 8002 |
| Generation | Token budget, compression, prompt assembly, LLM call | Citation correctness | 8003 |
| Citation Validator | Deterministic post-generation check of every citation tag | Any generation | 8004 |

Why split like this: ingestion is bursty and CPU/IO heavy (OCR, embedding);
retrieval is latency-sensitive and benefits from GPU-backed re-rankers;
generation is the most expensive per-call resource (LLM tokens). Each needs
its own autoscaling policy. Service-to-service calls are authenticated with
mTLS or signed service tokens in production; a shared internal API key via
`.env` is used locally (one-line swap later).

## 4. RAG pipeline

**Ingestion**
- OCR for scanned documents (Tesseract or managed OCR API) with a per-page
  confidence score; low-confidence pages are flagged for human review
  rather than silently indexed.
- Structure-aware chunking: by clause/section/heading (legal) or by
  note/encounter/section (medical, e.g. SOAP fields) — preserves the unit a
  citation needs to point to.
- Each chunk stored with: document ID, page, section/clause number,
  confidentiality tier, matter/patient ID, effective date.

**Retrieval**
- Hybrid search: dense vector similarity + sparse keyword/BM25 — legal and
  medical queries often include exact terms (statute numbers, drug names,
  dosages) pure semantic search can miss.
- Metadata filtering applied *before* ranking (tenant, matter/patient,
  confidentiality tier) — a user can never retrieve chunks outside their
  access grant, regardless of semantic similarity.
- Cross-encoder re-ranking on top-k candidates; the re-ranked, trimmed set
  is what flows downstream — itself a major token-optimization lever.

**Token optimization (Generation)**
1. Count before sending (tiktoken or provider tokenizer).
2. Trim by relevance, not truncation — below-threshold chunks are dropped
   entirely.
3. Compress what's kept (LLMLingua-style) while preserving the specific
   facts/figures/dates a citation might point back to.
4. Semantic caching for near-duplicate queries (GPTCache / Redis-backed).
5. Context reordering — most relevant chunks first/last, to counter
   "lost in the middle".

Every request logs tokens-in/out and which chunks were dropped at the trim
step, so a missed clause/note can be audited.

## 5. Prompt & citation enforcement

- System instructions fix the output format: every factual claim carries
  an inline `[chunk_N]` tag; the model says *"the provided documents do not
  address this"* rather than guess when grounding is missing; the answer
  ends with a structured citation list (chunk ID → document, page,
  section).
- Each retrieved chunk is injected with its own ID and metadata inline
  (`<chunk id="14" doc="Smith_Contract.pdf" page="12" section="4.2">...`)
  so citations map back deterministically.
- Few-shot examples include at least one correct-refusal example alongside
  correctly-cited examples.
- **Citation Validator** (separate deterministic service, not a second LLM
  call): parses every `[chunk_N]` tag, confirms the chunk was actually in
  the retrieved set, and runs a lightweight entailment check between the
  cited sentence and the chunk text. Outcome (pass / stripped-as-unverified
  / regenerate) is policy-driven per tenant and always logged.
- Prompt templates are versioned in a prompt registry, A/B tested on a
  held-out eval set before promotion to production.

## 6. Data layer

| Store | Holds | Notes |
|---|---|---|
| Vector DB (Qdrant/Weaviate/pgvector) | Chunk embeddings + metadata | Metadata filtering at query time for tenant/matter/patient isolation |
| Object storage (S3/Azure Blob, encrypted) | Original source documents | Versioned; retention policy per tenant/matter |
| Relational DB (Postgres) | Tenants, users, roles, document metadata, matters/patients | Source of truth for access control |
| Audit log (append-only) | Every query, retrieved chunks, generated answer, validation result | Immutable; required for e-discovery and compliance review |
| Cache (Redis) | Semantic query cache, session state, rate-limit counters | TTL'd; never holds raw PHI/privileged content beyond short-lived session state |

Encryption at rest and in transit everywhere; PHI/privileged fields are
additionally column-level encrypted in Postgres.

## 7. Security, compliance & governance

- **Tenant isolation:** row-level security in Postgres + metadata-filtered
  vector search; enforced at the query layer, not just the app layer.
- **HIPAA:** signed BAAs with third-party providers, PHI encrypted at
  rest/in transit, minimum-necessary access per role, audit logging of
  every patient-record access.
- **Privilege (legal):** privilege tagging at document and chunk level;
  privileged content excluded from cross-matter retrieval and from any
  fine-tuning/logging pipeline not strictly access-controlled to the
  matter team.
- **RBAC:** scoped to tenant × matter/patient × action; enforced at the
  gateway and re-checked at retrieval (defense in depth).
- **Model provider boundary:** contractual no-retention/no-training
  guarantees for third-party LLM APIs; self-hosted/VPC-isolated option for
  the most sensitive tenants.

## 8. Local-host substitutes

| Production | Local substitute | Notes |
|---|---|---|
| Qdrant/Weaviate (managed) | Qdrant, single-node container | Same client library both environments |
| S3/Azure Blob | MinIO | S3-compatible API, drop-in |
| Managed Postgres | Postgres container | RLS policies defined in migrations from day one |
| Redis (managed) | Redis container | Semantic cache, session state, rate-limit counters |
| Okta/Azure AD (OIDC/SAML) | NextAuth credentials provider or local OIDC mock | Swap provider config only |
| Append-only audit/WORM store | Postgres table, insert-only grants (no UPDATE/DELETE) | Good enough to prove the pattern locally |

No GPU dependency required locally — re-ranker/embedding default to small
CPU-friendly checkpoints, swappable to GPU-backed versions via `.env`. The
LLM call uses a real provider API key even locally, with a mockable client
for offline unit tests.

## 9. Build order

1. Scaffold + contracts — repo tree, `docker-compose.yml`, OpenAPI stubs,
   `libs/common/models`.
2. Ingestion → Retrieval, no generation yet.
3. Generation, uncited.
4. Citation Validator — wired in as a hard gate.
5. Frontend wiring.
6. Audit trail + RBAC, end-to-end.
7. Eval harness in CI.
8. Production path — `infra/k8s/`, `infra/terraform/`.

## 10. Infrastructure & deployment (production path)

Kubernetes (EKS/GKE/AKS), each FastAPI service its own deployment with
independent HPA policies (generation/retrieval scale on GPU/queue-depth,
gateway on request rate). Blue/green or canary deploys for generation
specifically, evaluated against citation-validation pass rate before full
rollout. Cross-region backup of vector store, object storage, and the
audit log (the audit log's durability requirements are often stricter than
the application data's).
