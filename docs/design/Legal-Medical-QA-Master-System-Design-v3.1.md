# Legal/Medical Document Q&A System — Master System Design & Delivery Report

**Version 3.1 · October 25, 2026 · Status: design baseline for review (nothing is built yet)**

*Consolidates and supersedes: "Build Architecture" (repo blueprint), "Enterprise Legal/Medical Document Q&A System — Architecture" (Oct 14, 2026), the partial "Technical Deep-Dive Report" (Oct 14, 2026) and "Multi-Tenant Identity, Access & Isolation Architecture" v2.1 (Oct 23, 2026). Identity provider: Auth0. Local-host first, enterprise-ready by configuration. No application code is included; short tool-configuration excerpts appear only where they define a quality gate.*

## 0. Document control

| Item | Value |
| --- | --- |
| Purpose | One authoritative design and delivery plan: system design, repository structure, twelve gated build stages, and a verification plan |
| Inputs reconciled | Four documents (listed above). All contradictions and defects found are recorded in Appendix A (DEF-01 to DEF-64) with the section that resolves each |
| Conventions | MUST / SHOULD / MAY carry RFC 2119 meaning. `D#` = decision (section 24). `DEF-##` = defect (Appendix A). `G#.#` = gate check (section 20). `§` = section |
| Vendor facts | Version and capability facts were checked against public sources on October 23, 2026 and are marked "verify at pin" where a lockfile or a vendor contract is the real authority |
| Revisions | 3.0 (October 23): consolidation of the four sources, 48 defects fixed. 3.1 (October 25): second full review pass, defects DEF-49 to DEF-64 fixed (principal view, validator-owned segmentation, pooled-connection compatibility, successor identity, key sealing and escrow, auth harness, server-side sessions), master system design diagram added (section 4.3), cross-component compatibility table added (section 4.8), gate profiles and feature flags added (section 19.6) for the MVP companion document |
| What is not here | Application source code, production credentials, vendor contracts, and legal advice. Counsel review is a required external step (section 25) |

## 1. Executive summary

### 1.1 What the system is

The system answers natural-language questions over large legal and medical document sets (contracts, case files, clinical documents, regulatory filings) and returns answers whose every claim carries a machine-verified, page- and clause-level citation. It refuses to answer when the documents do not support an answer. It is multi-tenant for law firms, hospital systems and similar customers, audit-logged end to end, and designed so that an unsupported answer is never shown to a user.

The retrieval-augmented pipeline (hybrid search, re-ranking, a hard token budget, a deterministic citation validator) comes from the earlier documents and is kept. This version adds what they lacked: who a tenant is, how people join, who may see what, how identity reaches every internal service, how keys are protected from accidental or malicious deletion, how the system is built stage by stage, and how each stage is proven with `pytest` and `ruff` on real data.

### 1.2 The model in one picture

```mermaid
flowchart TD
  subgraph PLATFORM["Platform (our company)"]
    OPS["Operators<br/>separate IdP, JIT access only"]
  end
  subgraph ORG["Organization = one customer: own KMS key, own Auth0 Organization"]
    SA["Super Admin<br/>plus optional co-owner"]
    subgraph WSA["Workspace A = isolation unit"]
      ADA["Admin A"]
      TA1["Tenant A1"]
      TA2["Tenant A2"]
      MA["Matters, documents, walls, audit"]
    end
    subgraph WSB["Workspace B = isolation unit"]
      ADB["Admin B"]
      TB1["Tenant B1"]
      MB["Matters, documents, walls, audit"]
    end
  end
  SA -- "governs, control plane only" --> ADA
  SA -- "governs, control plane only" --> ADB
  ADA -- "manages" --> TA1
  ADA -- "manages" --> TA2
  ADB -- "manages" --> TB1
  SA -. "no route, no policy, no key" .-> MA
  SA -. "no route, no policy, no key" .-> MB
  ADA -. "mutually invisible" .- ADB
  OPS -. "JIT, customer approval for content" .-> ORG
```

- **Organization (Super Admin).** The customer boundary: a law firm or hospital system. It has its own data partition, its own KMS key and its own Auth0 Organization. The Super Admin governs admins and never reads documents.
- **Workspace (Admin).** One per admin, many per organization, mutually invisible. An admin joins with the 64-character Organization Code and is activated after the Super Admin approves. Admins manage tenants and also do document work.
- **Tenant (member).** An end user inside exactly one workspace. A tenant joins with the admin's 32-character Admin Code and is activated after the admin approves.
- **Auth0 authenticates; our database authorizes.** Login, passkeys, MFA and organization membership live in Auth0. Role, workspace, status, grants, walls and approvals live in PostgreSQL, so suspension takes effect in seconds.
- **The database is the final authority; the vector store is not.** PostgreSQL row-level security decides what any caller may read. The vector store narrows search for recall and speed but is never trusted as a boundary (section 10.5).
- **No unverified text reaches a user.** Answers are released sentence by sentence only after the deterministic validator passes them, and no release happens before its audit record commits (section 11.6).

### 1.3 What changed in v3.0

| Change | Why | Where |
| --- | --- | --- |
| Key-deletion guardrails: two-person approval, long waiting windows, deletion protection, escrow and multi-Region backup, asymmetric powers (hard to destroy, easy to restore) | A per-organization KMS key makes one accidental or malicious deletion permanent | §12.5 to §12.8 |
| API table completed: first Admin Code, successor transfer, governance requests, break-glass, workspace state changes, walls, emergency access, operator plane | v2.1 flows had no endpoints | §15 |
| Platform operator access fully specified: identities, roles, JIT approval, expiry, recording | Mentioned in three places, never defined | §14 |
| State machines for organizations, workspaces, documents, access sessions and governance requests, kept as data and tested from that data | Only membership states existed | §6 |
| PostgreSQL is the authority; outbox re-indexing, drift reconciler and orphan-vector cleanup | Vector payloads lag after visibility or matter changes | §10.6 |
| Passkeys (phishing-resistant authentication) mandatory for Super Admins and admins; two approvers to delete an organization | Highest-power accounts need the strongest sign-in | §8.4, §12.7 |
| Ethical walls (explicit deny that beats every grant) and clinical emergency access | Legal and medical domain gaps | §5.6, §5.7 |
| Diagrams: hierarchy, onboarding, architecture, query flow, state machines, key hierarchy, destruction ritual, stage gates | v2.1 was text only | throughout |
| Corrections to defects found in v2.1 and the earlier documents, for example a tenant policy that exposed other users' private documents, HKDF keys that cannot be shredded independently, and a vector store wrongly counted as an isolation boundary | Logical contradictions and bugs | Appendix A |
| Twelve gated stages, real data only, `pytest` and `ruff` as mechanical gates, latest verified technology | Delivery plan requested | §19, §20 |

### 1.4 Delivery in twelve gated stages

Each stage MUST fully pass its gate before the next begins. Gates are cumulative: every earlier gate re-runs on every change (section 19.6).

| Stage | Name | Gate headline |
| --- | --- | --- |
| 0 | Foundation and real dependencies | Toolchain reproducible, `ruff` and `pytest` green, real Auth0, KMS, object store and corpus verified |
| 1 | Data layer and key management | RLS equals a reference oracle on random inputs; keys, shredding and KeyGuard proven |
| 2 | Identity and onboarding on Auth0 | All three onboarding paths, approvals, passkeys, governance requests work against a real Auth0 tenant |
| 3 | Gateway and internal trust | Token abuse rejected, revocation within SLO, context tokens enforced |
| 4 | Ingestion | Real documents ingested with provable chunk fidelity; index consistency proven |
| 5 | Retrieval | Scoped hybrid search with zero cross-scope leakage on provenance tests |
| 6 | Generation | Token budget invariants, scoped cache, injection resistance on live model |
| 7 | Citation validation and gated delivery | Zero unverified sentences released in live end-to-end runs |
| 8 | Frontend | Role routing, strict CSP, streaming torture tests, accessibility pass |
| 9 | Governance, audit, operators, lifecycle | Audit chain, alerts, JIT operator access, deletion ritual and restore drills pass |
| 10 | System verification | Isolation suite, load, chaos and evaluation floors met |
| 11 | Production readiness | External penetration test, counsel sign-off, vendor agreements, DR drill |

### 1.5 What this document proves and what it does not

It is a design. Every guarantee is a design claim until the gate that proves it passes (section 20). Three kinds of work cannot be closed by editing a document: performance under load, building and testing the code, and external review (penetration test, security architect review, counsel on HIPAA, privilege and retention, vendor agreements). Section 22 turns the performance risks into measurable budgets and section 25 lists the external items with owners and the stage that depends on each.

## 2. Scope, goals, non-goals and constraints

### 2.1 Goals

1. Every answer is grounded in retrieved source text; the system refuses when grounding is insufficient.
2. Every citation is machine-validated against the retrieved chunks before release, and what was released is provably what was validated.
3. Documents of 50 to 200+ pages are handled within a hard per-request token budget through structure-aware chunking, re-ranking and compression.
4. Strict multi-tenancy: organization, workspace, matter or patient, and document-visibility isolation, enforced in the database as final authority.
5. Compliance-ready for HIPAA (medical) and legal confidentiality and privilege, including audit, minimum-necessary access, ethical walls and emergency access.
6. Horizontally scalable retrieval and inference, independently of the stateless API and UI layers.
7. A local-host stack that runs the same code paths as production; moving to the cloud is configuration, not a rewrite.

### 2.2 Non-goals

- The system does not give legal or medical advice. It surfaces and cites what the documents say; disclaimers and human-review workflows are product surface.
- It does not make a wrong document right: a cited answer can still be wrong if the source is wrong. Human review stays in the workflow.

### 2.3 Constraints that shape the plan

| Constraint | Consequence |
| --- | --- |
| Real data from the first stage | No synthetic documents, no mocked stores, no mock identity provider (section 19.1). Real public documents, a real Auth0 tenant, real KMS |
| Auth0 handles sign-up and login | The sign-up screen is Auth0 Universal Login; our onboarding starts after the first authenticated session (section 7.1) |
| Latest technology | Versions verified in section 4.5; the lockfile is the authority; policy for adopting new majors in section 4.5 |
| `pytest` and `ruff` check correctness of everything implemented | Both are blocking gates in every stage; `ruff` also enforces the no-mocks and no-fake-data rule (section 19.3) |
| Local-host first | Everything except Auth0, KMS, the audit anchor bucket, the LLM provider and a test mailbox runs on one machine through Docker Compose |
| Do not code the project | This document is the blueprint; configuration excerpts are limited to gate definitions |

### 2.4 Assumptions

- A1. One organization has one Super Admin identity at creation; an optional co-owner can be added (section 7.5).
- A2. One user holds one membership in v1 (the schema allows more later, D7).
- A3. AWS is the reference cloud for managed services (KMS, S3, EKS); other clouds are reached through adapter interfaces (D23).
- A4. Customer data never enters local, CI or staging environments. Those environments use public documents only (section 19.1, rule R4).
- A5. Counsel will review privilege, retention, ethical-wall and HIPAA interpretations before any customer data is processed.
- A6. Documents are in English in v1; other languages need new evaluation sets and are out of scope for the first release.

## 3. Design principles and terminology

### 3.1 Principles

1. **Deny by default.** No policy means no rows. Missing context returns nothing, never everything.
2. **Derive, never accept.** `org_id`, `workspace_id`, role and scope come from the verified token (only `sub` and `org_id`) and the database (everything else), never from a request body, query string or client header.
3. **Assume one layer fails.** Every boundary is enforced at least twice, and the database is the last word.
4. **Control plane is not data plane.** Managing accounts does not imply reading documents.
5. **Least privilege applies to our own staff.** Operators have no standing access to customer content (section 14).
6. **Secrets are shown once and stored hashed.**
7. **Audit everything; keep sensitive text out of audit metadata and logs.**
8. **Local parity.** The same code path runs locally and in production; only adapters differ.
9. **Erasable by design.** Per-organization, per-workspace and per-document keys make deletion provable by key destruction.
10. **Fail closed on dependency failure.** If audit or the principal store is unreachable, requests stop at once; if the key service is unreachable, requests stop when the short-lived cached keys expire (section 10.4). Nothing proceeds unaudited or on stale authority.
11. **Asymmetric powers.** Restricting access, freezing, cancelling a deletion and creating a wall are one-person, instant actions. Relaxing access, lifting a wall, transferring ownership and destroying data require two people and a waiting window.
12. **No unverified release.** Generated text reaches a user only after deterministic validation and a committed audit record.
13. **State is data.** Every lifecycle is a declared state machine enforced in the database and tested from its declaration.

### 3.2 Terminology

The earlier documents use "tenant" for the customer. This report keeps your terminology: the customer is the **Organization** and **tenant** means the end user.

| Term | Meaning |
| --- | --- |
| Organization (org) | Top-level customer boundary created by one Super Admin. Owns one KMS key, one data partition and one Auth0 Organization |
| Super Admin | Account that created the organization. Governs admins; no access to tenants or content. A co-owner is a second Super Admin membership |
| Admin | Runs one workspace: manages its tenants and also does document work |
| Workspace | Isolation unit created for each admin. Holds documents, matters, memberships, walls and audit. Identified by `workspace_id` |
| Tenant | End user (attorney, paralegal, clinician, reviewer) inside exactly one workspace |
| Matter / patient scope | Sub-scope inside a workspace. Documents belong to one; tenants are granted access to them |
| Wall | Explicit deny for one user on one matter. Beats every grant, ownership and admin role |
| Organization Code | 64-character secret to request admin membership in one organization |
| Admin Code | 32-character secret to request tenant membership in one workspace |
| Principal | Verified identity of a request: user, org, workspace, role, status, authentication strength, scope hash |
| Context token | Short-lived signed JWT minted by the Gateway that carries the principal to one internal service |
| Platform operator | Our staff. Outside the organization hierarchy; no standing content access |
| Governance request | A two-person, time-windowed control-plane action such as successor transfer or organization deletion (section 6.7) |
| Gate | A set of mechanical checks (`ruff`, `pytest`, stage suites) that must all pass before the next stage |

### 3.3 Rename map for the earlier documents

| Earlier term | Becomes | Where it appeared |
| --- | --- | --- |
| `Tenant` model in shared models | `Organization` | Build Architecture, `libs/common/models` |
| `seed_demo_tenant.py`, "demo tenant" | `load_corpus` tool, "organization" (loaded through the real onboarding API, not SQL) | Build Architecture, scripts |
| "tenant-scope enforcement" middleware | principal resolver and route allow-list | Gateway |
| "tenant isolation" | workspace isolation nested inside organization isolation | all earlier documents |
| "tenant policy" for the citation behavior | organization policy (`on_fail`, `delivery_mode`) | Enterprise Architecture |
| `tenant_id` in code samples | `org_id` and `workspace_id`, taken from the principal, never from the request | Technical Deep-Dive |

## 4. System architecture

### 4.1 Three planes

| Plane | Contains | Who uses it | Key property |
| --- | --- | --- | --- |
| Data plane | Gateway data routes, Ingestion, Retrieval, Generation, Citation Validator, Audit reader | Admins and tenants | Handles document content; every access is scoped by workspace, matter, grants, walls |
| Control plane | Identity service, Gateway control routes, governance requests | Super Admins, admins | Manages accounts, codes, policies, states; physically cannot read content (no database policy covers content tables for control-plane roles) |
| Operations plane | Ops API, operator console, KeyGuard workflow | Platform operators | Separate ingress, separate identity provider, JIT access only, no content reach without customer approval (section 14) |

### 4.2 Service catalog

Every service is its own deployable, Docker image and database role. Ports are local-host defaults.

| Service | Port | Responsibility | Credentials it holds | Must never |
| --- | --- | --- | --- | --- |
| `frontend` (Next.js 16) | 3000 | UI and BFF route handlers; the only thing the browser talks to; owns the Auth0 session in a server-side session store | Auth0 client secret, session secret, Valkey ACL user for the session store only | Hold database, KMS, vector or object-store credentials |
| `gateway` | 8000 | Token verification, principal resolution, route allow-list, rate limits, idempotency, context-token minting, forwarding of the generation stream to the Validator, release of verified sentences | DB role limited to the `principal_v` view (which also exposes `scope_hash` and `scope_version`, section 16.2) and `audit_append`; Valkey ACL user; KMS permission to sign signer certificates only | Decrypt anything, read documents, call the Auth0 Management API, touch object storage |
| `identity` | 8005 | Onboarding, organizations, workspaces, memberships, join codes, governance requests, Auth0 sync, provisioning saga, revocation fan-out | DB role on control-plane tables only; Auth0 Management M2M; KMS for org key provisioning and control-field encryption; SMTP | Read documents, chunks, or audit payloads |
| `ingestion` (+ worker, indexer, reconciler) | 8001 | Upload intake, document lifecycle API, scan, parse, OCR, chunk, embed, write vectors, outbox re-indexing, drift repair | Object store read/write, Qdrant read/write key, DB role, KMS via keys library, embedding model | Serve queries |
| `retrieval` | 8002 | Scope resolution, hybrid search, Postgres cross-check, re-rank, retrieval ledger write | Qdrant **read-only** key, DB role, KMS decrypt for workspace keys, Valkey (scope cache) | Write vectors, call an LLM, read the object store |
| `generation` | 8003 | Token budget, compression, prompt assembly, LLM call, scoped answer cache | DB role (ledger and chunks under RLS), per-organization LLM provider key, Valkey (cache), KMS for cache key | Read vectors, bypass the ledger |
| `citation_validator` | 8004 | Sentence segmentation, deterministic validation of every sentence and tag, signed verdicts | DB role (read-only ledger and chunks), KMS decrypt for chunks, verdict-signing key | Call a generative LLM, write chunks |
| `audit` | 8007 | Audit read, search, export, hash-chain verification, hourly anchoring | DB audit-reader role, KMS decrypt for audit private keys, write access to the anchor bucket | Write ordinary audit events (writers use the database function) |
| `ops` | 8006 | Operator plane: JIT access requests, KeyGuard approvals, organization recovery, security holds | DB role on ops and governance tables; call to identity internal API | Read content; use customer Auth0 tenants |

Workers and scheduled jobs: `ingestion-worker` (parse, OCR, embed), `indexer` (applies the re-index outbox), `reconciler` (vector drift repair), `identity-worker` (saga steps, Auth0 sync, revocation fan-out), `audit-anchor` (hourly Merkle anchor), `retention` (retention and legal-hold enforcement).

All services write audit events through the `audit_append` database function using a payload sealed to a public key (section 13.2); none of them holds a key that can read audit payloads except the `audit` service.

### 4.3 Master system design

One diagram of the whole system: people, identity providers, tiers, services, stores, keys and external services. Solid arrows are runtime calls; dotted arrows are key or data-lifecycle relationships. An arrow into a store shows which service holds access to it and with what privilege.

```mermaid
flowchart TB
  subgraph PEOPLE["People"]
    SA["Super Admin and co-owner"]
    AD["Admin"]
    TE["Tenant"]
    OPR["Platform operators<br/>sre, support, security officer, key custodian"]
  end
  subgraph IDP["Identity providers"]
    A0["Auth0 customer tenant<br/>Universal Login, passkeys, MFA, Organizations"]
    A0P["Operator IdP<br/>separate tenant, passkeys, device certificate"]
  end
  subgraph PRES["Presentation tier"]
    FE["Next.js 16 BFF :3000<br/>proxy.ts, CSP nonces, generated client"]
    SS[("Valkey session store<br/>opaque session ID in the browser")]
  end
  subgraph CTRL["Control plane"]
    GW["Gateway :8000<br/>token check, principal, allow-list,<br/>context tokens, stream release"]
    ID["Identity :8005<br/>onboarding, codes, governance,<br/>provisioning saga, Auth0 sync"]
  end
  subgraph DATA["Data plane"]
    IN["Ingestion :8001<br/>upload, scan, OCR, chunk,<br/>worker, indexer, reconciler"]
    RT["Retrieval :8002<br/>scope, hybrid search, cross-check,<br/>re-rank, retrieval ledger"]
    GN["Generation :8003<br/>token budget, compression,<br/>prompt, LLM, scoped cache"]
    VL["Citation Validator :8004<br/>segmenter, checks V1 to V8,<br/>signed verdicts"]
    AU["Audit :8007<br/>read, verify, anchor"]
  end
  subgraph OPSP["Operations plane, separate ingress"]
    OC["Operator console"]
    OP["Ops API :8006<br/>JIT access, KeyGuard, recovery"]
  end
  subgraph STORES["Stores"]
    PG[("PostgreSQL 18 via PgBouncer<br/>RLS is the final authority")]
    QD[("Qdrant<br/>read-only key: retrieval<br/>read-write key: ingestion")]
    OS[("Object store<br/>encrypted objects")]
    VK[("Valkey<br/>principal cache, limits,<br/>pub/sub, answer cache")]
    WORM[("Object Lock bucket<br/>hourly audit anchors")]
    TS[("Tombstone ledger<br/>outside backups")]
  end
  subgraph KEYS["Keys and trust"]
    KMS["KMS<br/>organization CMK and replica,<br/>trust root"]
    ESC["Escrow CMK<br/>vault account, two custodians"]
  end
  subgraph EXT["Models and external services"]
    MOD["Embedding, re-rank, entailment<br/>models, self-hosted"]
    LLM["LLM provider<br/>per-organization boundary"]
    AV["ClamAV"]
    MAIL["SMTP"]
  end

  SA --> FE
  AD --> FE
  TE --> FE
  FE -- "login, PKCE" --> A0
  FE --> SS
  FE -- "Auth0 access token" --> GW
  OPR --> OC
  OC --> A0P
  OC --> OP

  GW -- "context tokens" --> ID
  GW -- "context tokens" --> RT
  GW -- "context tokens" --> GN
  GW -- "context tokens, token stream" --> VL
  GW -- "context tokens" --> IN
  GW -- "context tokens" --> AU
  GW --> VK
  GW -- "principal_v, audit_append" --> PG
  GW -. "signer certificate" .-> KMS

  ID -- "Management API" --> A0
  ID --> PG
  ID --> KMS
  ID --> MAIL
  ID -- "revocation publish" --> VK

  IN --> OS
  IN -- "read-write" --> QD
  IN --> PG
  IN --> AV
  IN --> MOD
  IN --> KMS

  RT -- "read-only" --> QD
  RT --> PG
  RT --> MOD
  RT --> KMS

  GN --> PG
  GN --> LLM
  GN --> VK
  GN --> KMS

  VL --> PG
  VL --> MOD
  VL --> KMS

  AU --> PG
  AU --> WORM
  AU --> KMS

  OP --> ID
  OP --> PG
  OP -- "KeyGuard approvals" --> KMS

  KMS -. "escrow copies" .-> ESC
  PG -. "deletion records" .-> TS
```

| Boundary | What crosses it | Enforced by |
| --- | --- | --- |
| Browser to presentation tier | An opaque session ID only | Server-side session store, strict CSP (section 17.3) |
| Presentation tier to Gateway | The Auth0 access token, which is never forwarded further | Token verification (section 8.5) |
| Gateway to services | A one-audience, 60-second context token plus the caller's own service credential | Section 9 |
| Services to stores | Scoped database roles, read-only versus read-write vector keys, per-service ACLs and KMS grants | Sections 9.2 and 10 |
| Everything to keys | Encryption-context-bound KMS calls; destruction needs two people and a window | Section 12 |
| Operators to customer data | Just-in-time, customer-approved, time-boxed, audited access only | Section 14 |

### 4.4 Query flow with gated release

```mermaid
sequenceDiagram
  autonumber
  participant U as Browser and BFF
  participant G as Gateway
  participant R as Retrieval
  participant N as Generation
  participant V as Validator
  participant D as PostgreSQL
  U->>G: POST /v1/query with Auth0 access token
  G->>G: verify token, resolve principal, check route allow-list
  G->>D: audit_append query.started (write-ahead)
  G->>R: search, context token for retrieval
  R->>D: set context, resolve scope, fetch chunks under RLS
  R->>R: hybrid search, cross-check, re-rank
  R->>D: insert retrieval record (request id, chunk refs, hashes)
  R-->>G: request id and counts
  G->>N: answer for request id, context token for generation
  N->>D: read ledger and chunks under RLS
  N->>N: token budget, compression, cache check, LLM stream
  N-->>G: internal token stream
  G->>V: forward token deltas, context token for validator
  loop each sentence the Validator completes
    V->>D: read ledger, compare chunk hashes
    V-->>G: signed verdict carrying the sentence text
    G->>D: audit_append segment released (hashes only)
    G-->>U: release verified sentence and its citations
  end
  G->>D: audit_append query.completed (sealed payload)
  G-->>U: final citation list and done event
```

Rules that follow from the diagram:

1. The Gateway orchestrates the fan-out; services never call each other and never forward user context. Retrieval hands off through the **retrieval ledger** in PostgreSQL, so chunk text never travels through the Gateway.
2. Generation and the Validator read chunks themselves, under RLS, by reference (chunk ID, version, content hash). A chunk that changed between retrieval and validation fails the hash comparison and the sentence is not released.
3. The Validator, not the Gateway, owns sentence segmentation, so the unit that is validated is exactly the unit that is released. The Gateway releases a sentence only when it holds a verdict signed by the Validator for that sentence (the verdict carries the sentence text and its hash) and this request. The final audit record stores the hash of everything released and the verdict signatures, so "what was released equals what was validated" is checkable later.
4. If an audit write fails at any point, the stream stops with an error. Nothing is released unaudited (principle 10).

### 4.5 Technology stack and version ledger

Versions below were checked on October 23, 2026. The lockfile (`uv.lock`, `pnpm-lock.yaml`) and the container image digests are the authority; Stage 0 records the exact resolved versions in `docs/versions.md` and gate G0.1 fails if they drift.

| Layer | Choice | Verified baseline | Why and notes |
| --- | --- | --- | --- |
| Python | 3.14 | 3.14 stable; 3.15 final was scheduled for October 1, 2026 | Newest interpreter with a full wheel ecosystem. Adopt 3.15 only after its first patch release and wheels for every dependency (policy below) |
| Package and project manager | `uv` workspace | 0.11.x (0.11.26 seen in June 2026) | One lockfile for all services and libs; `uv sync --frozen` in CI |
| Lint and format | `ruff` | 0.16.x (0.16.4 seen in August 2026) | 0.16 enables 413 rules by default and formats Python code blocks in Markdown; we select rules explicitly so upgrades never change the gate silently (section 19.3) |
| Test runner | `pytest` | 9.1.x (9.1.1 seen in June 2026) | With `pytest-asyncio`, `pytest-xdist`, `pytest-cov`, `pytest-randomly`, `pytest-timeout`, `hypothesis`, `schemathesis`, `pytest-playwright` |
| Type checking | `pyright` (blocking); `ty` informational | `ty` is still 0.0.x | Strict on `libs/` and security-critical services |
| Web framework and models | FastAPI latest 0.1xx, Pydantic 2.13+ | Pydantic 2.13.x (2.13.3 seen in April 2026); FastAPI supports Python 3.14 and has deprecated Pydantic v1 | Pydantic v2 only. Async end to end |
| Database access | SQLAlchemy 2 (async), `psycopg` 3, Alembic | latest at pin | Only through `lmqa_db`'s scoped session |
| Relational database | PostgreSQL 18 | 18.6 (August 2026); 18.5 was skipped for a regression; PostgreSQL 19 general availability was expected around October 2026 | Adopt 19 after GA plus its first minor release |
| Connection pooler | PgBouncer (transaction pooling) for the request path | latest (prepared-statement support needs 1.21 or later) | Request-path services connect through it with prepared statements configured for pooling. Workers that use `LISTEN`/`NOTIFY` or session advisory locks, and migrations, connect to PostgreSQL directly. The leak test for transaction-local context runs against the real pooler (G1.7) |
| Vector database | Qdrant | server 1.19.x (client 1.19.0 exists; 1.18.2 appears in Qdrant's own release table) | Upgrade one minor at a time as Qdrant requires. 1.16 added tiered multi-tenancy; 1.17 added audit logging |
| Cache, rate limits, pub/sub | Valkey | 9.1.x (May 2026) | BSD-licensed, RESP-compatible with Redis clients. Redis 8 is AGPL; Valkey avoids the licence review (D20) |
| Background jobs | Procrastinate (PostgreSQL-backed) | latest major at pin | Jobs are plain tables and SQL functions, so the application enqueues by calling the SQL defer function inside its own transaction, which removes "job ran before commit" races and fits the outbox pattern. Workers connect directly to PostgreSQL (not through the transaction pooler). Acceptance is proven by the Stage 0 spike (G0.13, D18). Fallback: Celery 5.6. Arq is excluded: the Taskiq project lists it as no longer actively maintained |
| Object storage | S3 in production; SeaweedFS locally | MinIO community edition entered maintenance mode in December 2025 | Local store chosen by a capability probe (versioning, presigned URLs, multipart, checksums). Application-level encryption makes SSE-KMS optional (section 12.3) |
| Frontend | Next.js 16.3.x, React 19.2, Node.js 24 LTS | Next.js 16 is the current major; security releases follow a published monthly schedule (16.3.7 was the September 30, 2026 entry on that schedule), so confirm the latest patch at pin | `proxy.ts` replaces `middleware.ts`; patch within each scheduled security-release window |
| Frontend auth | `@auth0/nextjs-auth0` v4 | 4.13 or later | `Auth0Client` in `lib/auth0.ts`; routes mounted at `/auth/*` by `proxy.ts`; app type "Regular Web Application" |
| Styling and UI | Tailwind CSS 4, shadcn/ui primitives | latest | Server components by default |
| Identity | Auth0 (Universal Login, Organizations, Actions, passkeys, M2M) | Plan check required (section 8.1) | HIPAA BAA is an Enterprise add-on; some attack protection is an add-on |
| Infrastructure as code | OpenTofu (Terraform-compatible) with the Auth0 and AWS providers | latest | Auth0 tenant configuration is code and drift-tested |
| Key management | AWS KMS (reference); OpenBao Transit locally for fast shredding tests | n/a | Both are real systems. Real KMS from Stage 0; OpenBao for the tests that need immediate key destruction (KMS enforces a 7 to 30 day wait) |
| Embeddings (candidates) | `bge-m3` (dense plus sparse), Qwen3-Embedding | chosen by the Stage 4 and 5 bake-off | Self-hosted by default so no document text leaves the boundary |
| Re-ranker (candidates) | `bge-reranker-v2-m3`, Qwen3-Reranker | Stage 5 bake-off | CPU-friendly default locally, GPU optional |
| Entailment model (candidate) | DeBERTa-v3 NLI cross-encoder | Stage 7 calibration | Pinned weights hash, CPU inference, fixed thresholds |
| Parsing and OCR (candidates) | Docling (layout-aware), Tesseract 5, `pypdfium2` | Stage 4 bake-off against a plain `pdfplumber` plus Tesseract baseline | Avoid AGPL parsers in a commercial product (PyMuPDF is AGPL or paid) |
| Malware scan | ClamAV | latest | Runs before any parser |
| Observability | OpenTelemetry, Grafana (Loki, Tempo, Prometheus) | latest | `org_id` and `workspace_id` as span attributes; never content |
| Load and browser tests | k6, Playwright | latest | k6 for load; Playwright with a virtual WebAuthn authenticator for real Auth0 login |
| Supply chain | CycloneDX SBOM, cosign keyless signing, GitHub artifact attestations, Trivy, gitleaks, Semgrep | latest | Release attestations of `ruff` and `uv` are verified in CI |

**Adoption policy.**

- New major runtime or database versions are adopted only after general availability, their first patch release, driver and wheel availability, and a full cumulative gate run on a branch.
- Security fixes: critical within 72 hours, high within 7 days, even if the cooldown has not elapsed.
- Other dependency updates wait a 7 to 14 day cooldown before merge so a malicious release is likely caught first.
- Container images are pinned by digest; base images are non-root and minimal.

### 4.6 Environments and what is real in each

| Concern | Local dev | CI | Staging | Production |
| --- | --- | --- | --- | --- |
| Identity | Auth0 `dev` tenant, real sign-ups | Auth0 `ci` tenant, same Actions and policies as production, applied from code | Auth0 `staging` tenant | Auth0 `prod` tenant with BAA where PHI is processed |
| Operator identity | n/a | `platform-staging` tenant | `platform-staging` | `platform-prod` (separate company IdP or Auth0 tenant) |
| Key management | AWS dev account KMS; OpenBao for shred tests | AWS CI account via OIDC federation (no static keys) | AWS staging account | AWS production account plus vault account for escrow |
| Audit anchor | Real S3 bucket with Object Lock (dev) | Real, CI account | Real | Real, WORM compliance mode |
| Postgres, Valkey, Qdrant | Compose containers | Service containers | Managed or Helm-deployed | Managed or Helm-deployed, HA |
| Object store | SeaweedFS | SeaweedFS | S3 | S3 |
| LLM and embeddings | Real provider key with a spend cap, or self-hosted model | Same, nightly live lane | Real, no-retention terms | Real, BAA or VPC-isolated per organization |
| Data | Public real corpus only | Public real corpus only | Public real corpus only | Customer data |
| Email | Real mailbox on a project-owned domain, read over IMAP | Same | Real | Real transactional provider |

`make doctor` verifies every real dependency (credentials present, reachable, budgets set) before any test runs and prints what is missing.

### 4.7 Allowed calls and import boundaries

Network rules (Compose networks locally, network policies in Kubernetes): the browser reaches only the frontend; only the frontend reaches the Gateway (and, for sessions, its own Valkey ACL user); only the Gateway reaches internal services; only `retrieval` (read-only) and `ingestion` (read-write) reach Qdrant; only `ingestion` and its workers reach the object store; only `identity` reaches the Auth0 Management API; only `ops` is exposed on the operator ingress.

Code rules, enforced in CI by `import-linter` contracts and `ruff` banned-API rules (G0.5, G0.11):

| Rule | Enforced by |
| --- | --- |
| No service imports another service's package | import-linter "independence" contract |
| `gateway` cannot import `lmqa_vectorstore`, `lmqa_objectstore`, chunk models, or decrypt functions of `lmqa_keys` | import-linter "forbidden" contract |
| `retrieval` cannot import `lmqa_objectstore` or any LLM client | same |
| `citation_validator` cannot import any LLM client, `lmqa_vectorstore` or `lmqa_objectstore` | same |
| `identity` cannot import chunk, document-content or audit-payload models | same |
| Only `lmqa_db` may create engines or connections; services use its scoped session, which refuses to run without a context | `ruff` TID251 banned API (`sqlalchemy.create_engine`, `psycopg.connect`) outside `lmqa_db` |
| Only `lmqa_vectorstore` may hold a Qdrant client; its query methods build the filter from a principal and have no unfiltered variant | import-linter plus unit tests |
| The frontend calls the Gateway only through the generated API client | ESLint restricted-imports rule |

### 4.8 Compatibility constraints and how the design handles them

Components that work alone can fail together. These are the cross-component constraints found in the second review pass, each with the gate that proves the handling.

| Constraint | Components | Handling | Gate |
| --- | --- | --- | --- |
| Transaction pooling breaks session state: `LISTEN`/`NOTIFY`, session advisory locks, session `SET`, and prepared statements without pooler support | PgBouncer, Procrastinate, `psycopg`, Alembic | Request path through the pooler with prepared statements configured for it; workers and migrations on direct connections; `audit_append` uses transaction-level locks | G0.13, G1.7 |
| A transaction-local setting leaves an empty string, not NULL, on a reused connection | PostgreSQL, PgBouncer, RLS policies | `NULLIF(current_setting(...), '')` in every policy | G1.3 |
| Next.js 16 replaced `middleware.ts` with `proxy.ts`; the Auth0 SDK v4 mounts `/auth/*` routes from it and needs a "Regular Web Application" client | Next.js, `@auth0/nextjs-auth0`, Auth0 | `proxy.ts` only; client type fixed in OpenTofu | G0.7, G8.1 |
| The SDK's default stateless session puts encrypted tokens in the browser and cannot be revoked server-side | `@auth0/nextjs-auth0`, Valkey | Server-side session store keyed by an opaque ID | G8.5 |
| A per-request CSP nonce forces dynamic rendering | Next.js 16, CSP | Accepted; static assets remain cacheable | G8.6 |
| Qdrant JWT scopes are per collection and the signing secret is the API key | Qdrant, `lmqa_vectorstore` | Filtering wrapper, separate read-only and read-write keys, Postgres as final authority, collection-per-workspace tier | G5.1, G5.4 |
| Hybrid dense plus sparse search needs named vectors and the Query API, so client and server versions must match | Qdrant, `qdrant-client` | Client pinned to the server's minor version | G0.4 |
| S3-compatible local stores differ from S3 on Object Lock and SSE-KMS encryption context | SeaweedFS, S3, KMS | Application-level encryption; Object Lock exercised only on real S3 | G0.4, G0.9 |
| KMS enforces a 7 to 30 day deletion window, which CI cannot wait for | AWS KMS, tests | OpenBao Transit for immediate-shred tests; real KMS for schedule, cancel and policy tests; `drill` tag for the annual full drill | G1.11, G9.6 |
| KMS signing quotas versus one signature per request | AWS KMS, Gateway | KMS signs hour-long signer certificates; instances sign tokens locally | G3.5 |
| ML libraries may lack wheels for the newest Python | Python 3.14, PyTorch, transformers, ONNX Runtime, Docling | Wheel check at lock time; the model-serving images may pin Python 3.13, recorded in `docs/versions.md` | G0.1 |
| `ruff` 0.16 enables 413 rules and formats Python code blocks in Markdown | `ruff`, docs | Explicit rule list; `docs/` excluded from the format check | G0.2 |
| Pydantic v1 is deprecated in current FastAPI | FastAPI, Pydantic | Pydantic v2 only; `pydantic.v1` is a banned import | G0.2 |
| Passkey and WebAuthn automation exists only in Chromium (virtual authenticator) | Playwright, Auth0 | Authentication flows run on Chromium; other browsers run non-authenticated smoke tests | G8.1 |
| The names Auth0 Actions see for authentication methods may change | Auth0 Actions | Contract test pins them | G2.7 |
| Presigned PUT with a required checksum needs matching headers and CORS from the browser | Object store, browser | Upload helper sets headers; CORS configured as code | G4.1 |
| SSE is broken by proxy buffering or compression | Next.js route handlers, ingress | `text/event-stream` excluded from buffering and compression; byte-boundary torture test | G8.4 |
| HPKE sealing needs an interoperable, maintained implementation | `lmqa_security` (writers), `audit` (reader) | RFC 9180 library, cross-implementation test vectors | G9.2 |
| Valkey is RESP-compatible, but ACL and pub/sub behavior must match what the clients expect | Valkey, Redis clients | Smoke and revocation tests run against Valkey itself | G0.4, G3.4 |
| Mermaid diagrams must render in the viewers people use | Documentation | Parsed in CI | G0.12 |


## 5. Roles, containment and access rules

### 5.1 Containment rules

```
Platform
└── Organization (Super Admin, optional co-owner)    org_id, own KMS key, own Auth0 Organization
    ├── Workspace A (Admin A)                        workspace_id
    │   ├── Tenants A1, A2 …                         private and matter-shared documents
    │   └── Matters / patients, documents, walls, audit
    └── Workspace B (Admin B)                        invisible to Admin A, and the reverse
        └── Tenants B1 …
```

- An organization contains workspaces; a workspace belongs to exactly one admin; a tenant belongs to exactly one workspace.
- Every table, vector payload, object key, cache key and audit event carries `org_id`; everything beneath an admin also carries `workspace_id`.
- Cross-workspace references are structurally impossible: foreign keys are composite (`org_id`, `workspace_id`, …), so a row cannot point into another workspace.
- Roles do not change in v1. A person is a Super Admin, an Admin or a Tenant; changing role means off-boarding and re-onboarding. This removes role editing as an escalation path.
- One user holds one membership in v1. The `memberships` table already supports several so multi-membership can be enabled later without a migration (D7).
- An organization has one primary Super Admin and at most one co-owner. Both hold the same `super_admin` role; the co-owner exists for two-person control (section 7.5).

### 5.2 Permission matrix

| Capability | Super Admin | Admin | Tenant |
| --- | --- | --- | --- |
| Create organization, edit organization settings | Own org | No | No |
| Generate or rotate the Organization Code | Yes (passkey, step-up) | No | No |
| Approve, reject, suspend, remove admins | Yes | No | No |
| See admin list, states, usage totals | Yes | Own profile only | No |
| See the tenant list | No (aggregate counts only) | Own workspace | No |
| Generate or rotate the Admin Code | No | Own workspace (passkey, step-up) | No |
| Approve, suspend, remove tenants | No | Own workspace | No |
| Create matters and grant tenants access | No | Own workspace | No |
| Create an ethical wall | No | Own workspace (instant) | No |
| Lift an ethical wall | Approves as second person (sees opaque IDs only) | Initiates | No |
| Upload documents, ask questions, read cited answers | No | Own workspace | Within grants |
| Read documents shared to a matter | No | Yes | If granted and not walled |
| Read a tenant's private documents | No | Only through a break-glass session (section 5.8) | Owner only |
| Invoke clinical emergency access | No | No (not needed) | Medical workspaces only (section 5.7) |
| Audit events | Org-level and admin-level events | Whole workspace | Own history |
| Audit payloads (question, chunk and answer text) | Never | Policy-controlled | Own |
| Approve or deny operator access to their data | Control-plane data only | Content in own workspace | No |
| Request organization deletion | Yes, with second approver | No | No |

### 5.3 The Super Admin boundary

The Super Admin owns the organization but stays out of the data plane. The boundary holds at three levels so a bug in one cannot leak tenant data:

1. **Gateway:** a route allow-list generated from `contracts/authz-matrix.yaml`. The Super Admin has no route to `/v1/query`, `/v1/documents`, or any workspace endpoint.
2. **Service layer:** no code path resolves tenant resources for that role.
3. **Database:** the `super_admin` policy set covers only `orgs`, `join_codes`, `workspaces` (metadata), `memberships` where the member is an admin, the Super Admin's own and co-owner membership rows, `governance_requests`, the aggregate-only `workspace_usage` table, and org-scope audit events. No policy covers documents, chunks, tenant memberships, walls or audit payloads, so the database returns nothing even if application code asks.

**Limit of this boundary.** The Super Admin decides who the admins are, so a dishonest owner could suspend an admin and name an identity they control as successor. No design removes that without removing the owner's authority, so the route is slow, loud and two-person: a successor transfer is a governance request (section 7.8) that needs a second approver, passkey step-up, a 72-hour cooling-off period, notice to every tenant and the outgoing admin, reset of `admin_can_read_private` to off, and an audit event the Super Admin cannot suppress. The guarantee is no direct access and no silent access, not that the owner is powerless.

### 5.4 Document visibility and the access decision

Each document is `private` (owner only) or `matter` (visible to tenants granted that matter, and to the admin). A document with visibility `matter` MUST have a `matter_id` (database CHECK constraint). `admin_can_read_private` defaults to false (section 5.8).

The access decision is a single function. The PostgreSQL policies, the vector filter builder and the test oracle all implement exactly this order; the Stage 1 gate proves the policies equal the oracle on random inputs (G1.4). **A rule earlier in the table wins over every later rule.**

| Order | Rule | Applies to | Result |
| --- | --- | --- | --- |
| 1 | The user's membership, the workspace or the organization is not `active` | everyone | Deny |
| 2 | A wall exists for (user, document's matter) | tenant and admin | **Deny** |
| 3 | The document is the user's own (owner) | tenant and admin | Allow |
| 4 | Role is admin and visibility is `matter` | admin | Allow (all tiers) |
| 5 | Role is tenant, visibility is `matter`, the user holds an unexpired grant on the matter, and the grant's `max_tier` is at or above the document's tier | tenant | Allow |
| 6 | Role is tenant, visibility is `matter`, and the user holds an active emergency exception on the matter, and the document's tier is at or below the emergency tier cap | tenant, medical workspaces | Allow (read and query only, no export) |
| 7 | Role is admin, visibility is `private`, `admin_can_read_private` is true, and the admin holds an active break-glass session | admin | Allow (read and query only) |
| 8 | Anything else | everyone | Deny |

Super Admin and operators never reach this table: they have no policy on content tables.

Two corrections to v2.1 are built into this table: rule 5 requires `visibility = 'matter'` (v2.1's tenant policy let a tenant read other users' private documents inside a granted matter, DEF-02), and the grant carries a tier ceiling so "allowed confidentiality tiers" has a source of truth (DEF-17).

### 5.5 Confidentiality tiers

Documents and chunks carry `confidentiality_tier`: 1 `internal`, 2 `confidential`, 3 `privileged_or_phi`, 4 `restricted` (for example sealed matters, VIP or employee patient records). A grant states the highest tier the tenant may read. Uploads cannot set a tier above the uploader's own ceiling on that matter. Tier 4 is never reachable through emergency access.

### 5.6 Ethical walls (legal workspaces)

A wall is an explicit deny for one user on one matter. It exists because "granted" and "owner" are not enough in legal practice: conflicts arise after grants exist, and a lateral hire may need to be screened from a matter. Counsel confirms which rules apply per jurisdiction (for example screening under ABA Model Rule 1.10 and local variants).

- **Precedence.** Walls win over grants, ownership, the admin role and emergency access (rule 2 above). A walled user who owns a document in the walled matter cannot read it.
- **Scope of effect.** Walls apply in PostgreSQL policies, in the vector filter (`must_not` on the matter), in the scope hash that keys caches, and in the citation side panel. They take effect on the next request; open streams are cut within the revocation SLO (section 8.6).
- **Asymmetry.** Creating a wall is one admin, instant. Lifting a wall is a governance request (`wall_lift`) approved by a second person, the Super Admin, who sees only opaque IDs and a reason code, with a 24-hour wait and notice to the affected user.
- **Walls on admins.** An admin can be walled. Only the Super Admin can initiate lifting a wall on an admin, with a second approver.
- **Visibility of walls.** The existence of a wall is itself sensitive. Walls are readable only by the admin of the workspace and, as opaque rows, by the second approver during a lift. The walled user sees only "no access".
- **Existing documents.** A new wall does not delete anything. It hides the matter's documents from that user at query time; no document row or vector payload changes, so there is nothing to re-index.

### 5.7 Clinical emergency access (medical workspaces)

The HIPAA Security Rule lists an emergency access procedure as a required implementation specification (45 CFR 164.312(a)(2)(ii)); counsel confirms the exact policy. The system implements a time-boxed, loud override:

| Property | Value |
| --- | --- |
| Availability | Only in workspaces of deployment type `medical` or `both`, and only if the admin enabled `emergency_access` in workspace policy (default off, recommended on for clinical organizations) |
| Who | Any active tenant without a grant to the patient scope |
| Request | Reason code from a fixed list (for example "treatment emergency") plus a free-text note |
| Effect | Creates an `access_exceptions` row (kind `emergency`) for that patient or matter, expiring in 60 minutes; read and query only; no export; tier cap 3 (tier 4 and walled matters stay denied) |
| Controls | At most 5 per user per day; immediate notification to the admin; every query inside the window flagged in audit as break-glass severity |
| Review | A post-hoc review task is created for the admin and must be closed within 72 hours; unreviewed items alert at 48 hours and again at 72 hours |
| Revocation | The admin can end any emergency exception at once; ending bumps the scope version and publishes the invalidation message (section 8.6) |

### 5.8 Break-glass reading of a tenant's private documents

With `admin_can_read_private` off (the default) no admin can read private documents. Enabling the flag is a governance request (`private_read_enable`, approved by the Super Admin, 24-hour wait, all tenants notified), because it changes the privacy promise made to tenants. Even when enabled, each use requires a **break-glass session**: the admin states a reason, passes passkey step-up, and receives a session of at most 60 minutes. Rule 7 in section 5.4 checks both the flag and an active session, so "each access is recorded" holds in the database, not just in the application. Sessions are visible to the affected tenant in their own audit history.

### 5.9 Owner-linked admin identities

D1 recommends that a Super Admin who also wants to do document work registers a second identity as an admin. That second identity is a different person-in-the-system but may be the same human, which weakens two rules: nobody approves their own membership, and the Super Admin never sees content. The design cannot detect two identities held by one human, so it makes the situation explicit instead of pretending it cannot happen (DEF-13):

- The Super Admin declares the identity as **owner-linked** at approval time; the flag is stored and audited.
- The workspace shows its tenants a banner: "This workspace is administered by the organization owner."
- If a co-owner exists, the co-owner approves owner-linked admins instead of the Super Admin.
- The two identities MUST use different verified emails and different registered authenticators; the audit trail links the approval event to the owner-linked flag.
- This remains a residual risk (section 25).

## 6. Lifecycle state machines

### 6.1 Principles

Every lifecycle in this section is declared in `contracts/state-machines.yaml`: states, allowed transitions, who may trigger each, guard conditions and side effects. The declaration is the single source for three things:

1. **Database enforcement.** Each stateful table has a transition table and a trigger that rejects any change not listed, so an application bug cannot skip a state.
2. **Service enforcement.** The `lmqa_models` package generates the transition guards from the YAML.
3. **Tests.** A generated test suite tries every legal transition as an authorized actor (must succeed), every legal transition as an unauthorized actor (must fail with 404 or 403) and every illegal pair (must fail), against the real database and API (G1.9, G2.9, G9.9).

### 6.2 Membership

```mermaid
stateDiagram-v2
  [*] --> pending_approval : valid code submitted
  pending_approval --> active : approve
  pending_approval --> rejected : reject
  active --> suspended : suspend or cascade
  suspended --> active : reactivate
  active --> removed : remove
  suspended --> removed : remove
  rejected --> [*]
  removed --> [*]
```

| State | Meaning | Data access | Sessions |
| --- | --- | --- | --- |
| `onboarding` (not stored) | Authenticated, no membership yet | None | Onboarding scope only |
| `pending_approval` | Valid code submitted, waiting for the approver | None | Status page only |
| `active` | Approved | Per role, grants, walls | Normal |
| `suspended` | Paused by an approver or by cascade (reason code stored: `admin_action`, `workspace_frozen`, `org_frozen`, `security_hold`) | None; data retained | Revoked at once |
| `rejected` | Approver declined | None | Revoked |
| `removed` | Off-boarded | None; data handled per section 7.7 | Revoked |

The approver is the Super Admin for admins and the workspace admin for tenants. Nobody approves or changes their own membership. The Super Admin's first membership is created `active` by the provisioning saga, and the only way to add a Super Admin afterward is the co-owner flow.

### 6.3 Workspace

```mermaid
stateDiagram-v2
  [*] --> pending : admin request
  pending --> provisioning : approve
  pending --> rejected : reject
  provisioning --> active : provisioned
  active --> frozen : admin suspended or removed, org frozen, or org deleting
  frozen --> active : reactivate or successor effective
  frozen --> sealed : 30 days with no successor, or org deletion grace ended
  sealed --> frozen : unseal, two-person
  sealed --> destroyed : destroy, two-person, retention ended, no hold
  rejected --> [*]
  destroyed --> [*]
```

| State | Meaning | Who can read data | Notes |
| --- | --- | --- | --- |
| `pending` | Admin requested; awaiting Super Admin | Nobody; no partition yet | Pending workspace removed on reject |
| `provisioning` | Approved; partition, keys and quotas being created | Nobody | Idempotent saga; stays here and retries if a step fails |
| `active` | Normal operation | Per section 5.4 | |
| `frozen` | Admin suspended or removed, or organization frozen | Nobody; sessions revoked; data retained | Admin Code disabled; tenants carry `workspace_frozen` |
| `sealed` | Frozen with no decision after 30 days, or organization deletion grace ended | Nobody, including operators | Content keys are re-wrapped under an escrow key that needs two custodians to release (section 12.6). Reversible until destroyed |
| `destroyed` | Keys destroyed, vectors and objects deleted | Nobody | Destruction record kept in audit metadata |

### 6.4 Organization

```mermaid
stateDiagram-v2
  [*] --> pending : sign-up and provisioning
  pending --> active : provisioned and approved
  pending --> rejected : operator rejects
  active --> frozen : operator hold
  frozen --> active : operator release
  active --> deletion_pending : org_delete approved
  frozen --> deletion_pending : org_delete approved
  deletion_pending --> active : cancel, one person
  deletion_pending --> sealed : 30-day grace ended
  sealed --> frozen : restore, one person, key deletion cancelled
  sealed --> destroyed : provider window ended, destroy executed
  rejected --> [*]
  destroyed --> [*]
```

| State | Meaning | Access |
| --- | --- | --- |
| `pending` | Saga running, and in production awaiting operator approval (D9) | None for everyone except the Super Admin, who may sign in to enroll authenticators and see the status page; no governance action and no code generation until `active` |
| `active` | Normal | Per roles |
| `frozen` | Operator hold: non-payment, security hold or legal order. Reason code stored | All sessions revoked; read-only export window for the Super Admin and admins; nothing deleted |
| `deletion_pending` | 30-day grace after an approved `org_delete` | Export allowed; everything else blocked; one person can cancel |
| `sealed` | Grace over; all content keys disabled; KMS deletion scheduled at the provider maximum (30 days) | Nobody. Restoring needs one person plus the key custodian's cancel action |
| `destroyed` | Keys, vectors, objects, and Auth0 Organization removed | None; destruction record remains |

### 6.5 Documents and index state

Document `status`: `uploading` → `scanning` → `parsing` → (`ocr_review` when any page is below the confidence threshold) → `indexing` → `indexed`; side exits `failed`, `held` (owner removed; section 7.7), `deleting` → `deleted` (tombstone kept). Each document version has `index_state`: `in_sync`, `stale` (Postgres changed, vector payload not yet updated), `reindexing`. Only `indexed` plus `in_sync` content is searchable; `stale` content is searchable only if Postgres still allows it (section 10.6).

### 6.6 Join codes

States: `active` → `rotated`, `expired`, `exhausted`, `disabled`, `revoked`. Rotation moves the old code to `rotated` instantly. `disabled` is set by cascade (workspace frozen). A use is counted only when a membership is created (idempotent).

### 6.7 Governance requests

A governance request is the single mechanism for control-plane actions that need two people and a waiting window. State: `requested` → `approved` → `waiting` → `executable` → `executed`; exits `rejected`, `cancelled`, `expired` (approvals expire after 72 hours), `failed`. The initiator can always cancel (restoring direction). Approvers must be distinct humans (distinct identities and distinct authenticators) from the initiator and each other, and each approval needs passkey step-up within 5 minutes.

| Kind | Initiator | Second approver | Wait | Effect |
| --- | --- | --- | --- | --- |
| `successor_transfer` | Super Admin | Co-owner, or an operator `security_officer` after out-of-band confirmation with the contract signatory | 72 h | Re-parents a frozen workspace to the pending successor membership (section 7.8); resets `admin_can_read_private`; notifies tenants and the outgoing admin |
| `private_read_enable` | Admin | Super Admin (control-plane approval) | 24 h | Enables break-glass capability; notifies all tenants |
| `wall_lift` | Admin (wall on a tenant) or Super Admin (wall on an admin) | Super Admin (wall on a tenant) or operator `security_officer` after out-of-band confirmation (wall on an admin) | 24 h | Removes the wall; notifies the affected user |
| `workspace_unseal` | Super Admin | Co-owner or operator `key_custodian` | 72 h | `sealed` → `frozen` |
| `workspace_destroy` | Super Admin | Co-owner or operator, plus `key_custodian` at the key stage | 30 days after approval, and only when retention has ended and no legal hold exists | `sealed` → `destroyed` |
| `org_delete` | Super Admin | Co-owner, or contract signatory verified by an operator; `key_custodian` at the key stage | 30-day grace plus the provider's deletion window | Section 12.7 |
| `owner_recovery` | `operator_support`, on the request of the organization's authorized signatory | `security_officer` plus a different `operator_support` lead (three distinct operators in total), with notice to every admin and the co-owner, who can veto | 72 h | Replaces a lost Super Admin identity |
| `co_owner_set` | Super Admin | The invitee accepts with a passkey | 72 h | Adds the co-owner membership |

*Note on `wall_lift` for a wall on an admin.* An admin cannot approve lifting a wall on themselves, and the Super Admin is the only other human with authority over the workspace, so for that case the Super Admin initiates and an operator `security_officer` approves after the organization confirms out of band. This keeps the two-person rule without giving one person sole authority over a wall that may exist to screen them.

### 6.8 Access sessions

Break-glass (admin private read), clinical emergency access and operator JIT access share one lifecycle: `requested` → `approved` (or `denied`) → `active` → `expired` or `revoked` → `reviewed`. Each has a hard expiry, a reason, and audit events visible to the affected party. The table in section 14.4 lists the per-type limits.

## 7. Onboarding, codes and lifecycle events

### 7.1 Common entry

1. The user signs up or logs in through Auth0 Universal Login. Email verification is mandatory; MFA enrollment is mandatory (privileged roles need a passkey or a WebAuthn factor, section 8.4).
2. A first login with no membership receives a token for a separate Auth0 API (audience `onboarding`) whose organization setting is "deny", exposing only onboarding endpoints. The main API's organization setting is "require", so an organization-less token cannot reach it.
3. The onboarding screen offers three cards: **Create organization** (Super Admin), **Join as admin**, **Join as tenant**. The card only selects a flow. The role is derived from the proof submitted (a valid code of the matching kind) and never from a client-supplied field.
4. On success the identity service writes the membership. A Super Admin is added to the new Auth0 Organization at once. An admin or tenant is added, with the Auth0 role, only when approved, so a pending user can never hold an organization-scoped token. The BFF then starts a new authorization request naming the Auth0 organization (silent if an Auth0 session exists, because a refresh token cannot gain an organization later) and receives `org_id`.

### 7.2 Path A: Super Admin creates an organization

No code is needed. The user supplies an organization name, deployment type (legal, medical, both) and data region. Abuse controls: verified email, mandatory MFA, disposable-domain blocking, per-IP creation limits, and in production operator approval (D9).

```mermaid
sequenceDiagram
  autonumber
  participant U as User
  participant A as Auth0
  participant B as BFF
  participant I as Identity
  participant K as KMS
  participant D as PostgreSQL
  U->>A: sign up, verify email, enroll MFA
  A-->>B: onboarding-scope token
  B->>I: POST /v1/onboarding/organization with idempotency key
  I->>D: insert org in state pending, genesis audit entry
  I->>K: create org key, replica, key policy, deletion guards
  I->>K: generate and wrap control key, write escrow copy
  I->>A: create Auth0 Organization
  I->>D: register resources, default policies, Super Admin membership active
  I->>A: add Super Admin to Organization, mark privileged
  I->>D: org active, or awaiting operator approval in production
  I-->>B: created
  B->>A: new authorization request naming the organization
  A-->>U: passkey enrollment required for privileged role
  U->>B: enroll two authenticators, then generate Organization Code
```

The saga is idempotent: each step records completion, a failure triggers compensation, and the organization stays `pending` and invisible until every step succeeds. The Organization Code is **not** generated in the saga (v2.1 would have held the plaintext until display, DEF-29); the Super Admin generates it with `POST /v1/org/code` once two authenticators are registered, and it is shown once. "Clean database" is satisfied logically (an empty partition under its own key); a physically dedicated database is the silo tier (section 10.10).

### 7.3 Path B: Admin joins an organization

The person enters the 64-character Organization Code. The identity service validates it, then creates a membership in `pending_approval` and a workspace in `pending`. The Super Admin sees the request in Manage Admins (or the co-owner for owner-linked requests) and approves or rejects. Approval moves the workspace through `provisioning` to `active` (partition, workspace content key, quotas), adds the user to the Auth0 Organization with the admin role, and sets `app_metadata.privileged` so the next authorization forces passkey enrollment. The Admin Code is generated only when the new admin selects Generate Admin Code (`POST /v1/workspace/code`) after their first privileged login; it is shown once to that admin and is never held in plaintext while waiting. Until then the user sees an "awaiting approval" page and has no data access.

The approval step exists because the Organization Code is a shared secret that will eventually be pasted into the wrong chat; without approval a leak is an admin takeover, with it a leak is a nuisance request. A stricter option is an invite-bound code locked to one email address.

```mermaid
sequenceDiagram
  autonumber
  participant P as Person
  participant B as BFF
  participant I as Identity
  participant S as Approver
  participant A as Auth0
  P->>B: submit code, Organization Code or Admin Code
  B->>I: join-admin or join-tenant, onboarding token
  I->>I: lookup by public id, compare keyed hash in constant time, rate limits
  I-->>B: identical response whether valid or not, membership pending if valid
  I-->>S: notification, pending request appears in manage page
  S->>I: approve with passkey step-up, or reject
  I->>A: add to Auth0 Organization, assign role, mark privileged if admin
  I->>I: principal version bump, membership active
  P->>B: sign in again naming the organization
  B-->>P: access per role and grants
```

### 7.4 Path C: Tenant joins a workspace

The person enters the 32-character Admin Code. The service resolves code → workspace → admin → org, shows "You are joining the workspace of [admin name]" for confirmation, and creates a `pending_approval` membership. The admin approves in Manage Tenants and can assign grants in the same step. Per-workspace policy can switch approval to `auto` or `domain_allowlist` (auto-approve only for listed email domains), but `manual` is the default for legal and medical workspaces. The confirmation screen is served by a preview endpoint that does not consume a use and returns the same error as a failed join for any invalid code.

### 7.5 Co-owner

A Super Admin can invite one co-owner (`co_owner_set`): an email-bound invite, accepted by the invitee with passkey registration, effective after a 72-hour cooling-off with notice to all admins. The co-owner holds the same `super_admin` role. Production organizations SHOULD designate a co-owner within 14 days of activation; without one, organization deletion and successor transfer fall back to the operator-verified second approver (section 6.7).

### 7.6 Code specification

| Property | Organization Code | Admin Code |
| --- | --- | --- |
| Length | 64 characters | 32 characters |
| Alphabet | Crockford Base32, upper case, displayed in groups of 8 | Same |
| Structure | 8-character public lookup ID, 55 secret characters, 1 Luhn mod-32 check character | 8-character public lookup ID, 23 secret characters, 1 Luhn mod-32 check character |
| Secret entropy | 275 bits (55 characters at 5 bits each) | 115 bits (23 characters at 5 bits each) |
| Generated by | Identity service, CSPRNG, at the owner's request | Same |
| Held by | Super Admin (shown once) | Admin of that workspace (shown once) |
| Bound to | `org_id` | `workspace_id` |
| Grants | A pending admin membership | A pending tenant membership |
| Stored as | Keyed HMAC-SHA-256 of kind plus full code, using a versioned server-side pepper held in the secret manager; plaintext lookup ID | Same |
| Display afterward | Lookup ID, creation and expiry dates, uses remaining. Not the last characters | Same |
| Default expiry / max uses | 30 days / 25 | 90 days / 100 |
| Rotation | Instant; pending requests are re-reviewed, not auto-approved | Same |

v2.1 claimed about 315 and 155 bits and also displayed the last four characters; the 8-character lookup ID is stored in plaintext, so only the secret portion counts, and showing trailing characters leaks more (DEF-11). Both secret portions are still far beyond brute force, so controls concentrate on **leakage and handling**:

- **Transport.** Invite links put the code in the URL fragment (`#`), which browsers never send to servers; the page reads it, removes it from history and posts it in a request body. The shared logging library redacts `code` fields. `Referrer-Policy: no-referrer` on onboarding pages.
- **Rate limits.** 5 failed attempts per user per 15 minutes, 20 per IP per hour, and a circuit breaker per lookup ID. Every failure returns the same "code invalid or expired" message; the true reason goes to the audit log only.
- **Verification.** Look up by public ID, then compare the HMAC in constant time.
- **Typos.** The check character lets the client catch mistakes before sending.
- **Alerts.** Notify the code owner on first use from a new country, bursts of use, or use right after a failed-attempt spike.

### 7.7 Lifecycle events and effects

| Event | Triggered by | Immediate effect | Data and codes |
| --- | --- | --- | --- |
| Organization created | New Super Admin | Org `pending` → `active` (production: after operator approval) | Org key, partition created; Organization Code generated later by the owner |
| Admin request submitted | Person with the Organization Code | Membership `pending_approval`; workspace `pending`; no access | Use counted on success only |
| Admin approved | Super Admin | Workspace `provisioning` → `active`; passkey enrollment forced | Admin Code generated by the admin after first privileged login |
| Admin rejected | Super Admin | Membership `rejected`; sessions revoked | Pending workspace removed |
| Admin suspended | Super Admin | Workspace `frozen`; admin and all tenants lose access in seconds | Data retained; Admin Code disabled; tenants `suspended` with `workspace_frozen` |
| Admin reactivated | Super Admin | Admin `active`, workspace `active`; only cascade-suspended tenants restored | Admin Code stays disabled until rotated |
| Admin removed | Super Admin | Workspace `frozen` for a 30-day decision window | Successor via `successor_transfer`; with no successor the workspace becomes `sealed`, unreadable by anyone, destroyed only after retention and legal hold end |
| Organization Code rotated or leaked | Super Admin | Old code dead at once | Pending requests re-reviewed; active admins unaffected |
| Admin Code rotated or leaked | Admin | Old code dead at once | Pending tenant requests re-reviewed; active tenants unaffected |
| Tenant approved | Admin | Membership `active`; grants applied | Scope hash refreshed |
| Tenant suspended or removed | Admin | Sessions revoked in seconds; streams cut | Private documents move to `held`. The admin sees only a metadata-only holding queue (ID, size, date, matter label, never title or text, DEF-12) and can delete them (key destroyed) or reassign them to another tenant on the same matter without opening them; reassigning to the admin personally is a break-glass access. Matter-shared documents are unchanged |
| Tenant leaves or requests deletion | Tenant | Membership closed | Authored content per retention schedule and legal hold |
| Wall created / lifted | Admin / governance request | Takes effect next request; streams cut | Notifications per section 5.6 |
| Emergency access invoked | Tenant | Time-boxed exception; admin notified | Review within 72 h |
| Super Admin loses access | Owner | Organization keeps running; no governance changes | `owner_recovery`, or the co-owner |
| Organization frozen | Operator | All sessions revoked; read-only export window | Nothing deleted |
| Organization deleted | Super Admin plus second approver | `deletion_pending` (30 days), then `sealed`, then `destroyed` | Section 12.7 |

### 7.8 Successor transfer

When an admin is removed or suspended the workspace is `frozen`. Because every user holds one membership and every admin one workspace in v1, the successor is always a **new admin identity**, never an existing admin. The Super Admin issues an email-bound **successor invite** (a join code of kind `successor`, bound to the frozen workspace); the invitee signs in, submits it, and a membership in `pending_approval` is created linked to the frozen workspace instead of a new one (no second workspace is created). The Super Admin then starts `successor_transfer` naming that pending membership. After the second approval and the 72-hour cooling-off, the transfer executes: the workspace is re-parented to the new admin, the membership becomes `active`, `admin_can_read_private` is reset to off, all walls and break-glass sessions are re-validated, every tenant and the outgoing admin receive notice, and an audit event is written that the Super Admin cannot suppress. If no successor is named within 30 days the workspace becomes `sealed`.

## 8. Authentication with Auth0

### 8.1 Responsibility split and plan check

| Concern | Auth0 | Our platform |
| --- | --- | --- |
| Sign-up, login, password policy, breached-password and bot protection, SSO connections | Owns | Consumes |
| Passkeys and MFA factors | Owns the credentials | Requires a minimum authentication strength per role (section 8.4) |
| Organization membership | Holds the Auth0 Organization | Mirrors it in `orgs.auth0_org_id` |
| Role, workspace, status, grants, walls, approvals | Role label only | **Source of truth (PostgreSQL)** |
| Suspension and revocation | Block user, end sessions, remove from Organization | Per-request status check, principal version, pub/sub invalidation |

**One Auth0 Organization per our Organization**, not per workspace: per-customer SSO and branding are organization-level concerns, and Auth0 Organizations are flat, so the workspace level lives in our database. Three Auth0 roles exist (`super_admin`, `admin`, `tenant`). Roles are defined once per Auth0 tenant and assigned per organization membership (v2.1 said each organization has "its roles", which is not how Auth0 models roles, DEF-19). Only the identity service assigns them.

Plan facts checked on October 23, 2026 (confirm with the vendor before purchase):

- HIPAA BAA is an add-on for Enterprise plans, so any deployment that processes PHI needs that plan and add-on before the first real clinical document (D8).
- Bot Detection, Credential Guard, Adaptive MFA and the Highly Regulated Identity features are add-ons; the Actions allowance is limited by plan (this design needs four Actions or fewer).
- Machine-to-machine access is plan-limited; the identity service's Management API client and any CI automation need it, so the `ci` tenant must be on a paid plan with enough M2M tokens for the test load.
- Auth0 tenants are regional; an organization with a different residency requirement may need its own Auth0 tenant.
- Custom domain (for `login.<product-domain>`) keeps cookies, branding and CSP on our domain.

### 8.2 Tenants and configuration as code

Four Auth0 tenants (`dev`, `ci`, `staging`, `prod`) plus operator identity (section 14). Every setting is OpenTofu code (Auth0 provider) in `infra/auth0/`: tenant flags, session lifetimes, the database connection (passkeys enabled, password policy, breached-password detection), two APIs, two applications, three roles, Actions, MFA policy, attack protection, email provider, branding, log streaming to the SIEM. A CI job runs `tofu plan` against each tenant and fails on drift (G0.7).

| Object | Configuration |
| --- | --- |
| API `main` | Audience `https://api.<product-domain>`; RS256; **Organization required**; access token lifetime 10 minutes; refresh-token rotation with reuse detection |
| API `onboarding` | Audience `https://onboarding.<product-domain>`; **Organization denied**; only onboarding endpoints accept it |
| Application `web-bff` | Regular Web Application (not SPA), Authorization Code with PKCE, allowed callback and logout URLs exact-match only |
| Application `identity-m2m` | Machine-to-Machine; Management API scopes: read and update users, organizations and members, roles, authentication methods, sessions and refresh tokens, nothing else |
| Connection | Database connection with passkeys enabled; **no social connections** for legal and medical deployments; sign-up allowed (no access without a membership); disposable-domain blocking in a pre-registration Action |
| MFA policy | "Always"; factors: WebAuthn (roaming and platform), TOTP, recovery code. SMS, voice and email OTP are disabled (SIM-swap and phishing exposure) |
| Actions | `enforce-auth-strength` (post-login), `block-unverified-email` (post-login), `disposable-domain-block` (pre-registration). Actions never call our backend, so a backend outage cannot break login |

### 8.3 Login flow

1. The browser talks only to the Next.js BFF, which uses `@auth0/nextjs-auth0` v4 with Authorization Code plus PKCE. The SDK is configured with a **server-side session store** (Valkey, values encrypted with the session secret): the browser holds only an opaque, httpOnly, SameSite session ID, tokens never leave the server, and a session can be deleted centrally for revocation and "sign out everywhere". The SDK's default stateless cookie session would put the encrypted tokens in the browser and could not be revoked server-side (DEF-58).
2. The post-login Action blocks unverified emails and enforces authentication strength (section 8.4). It adds namespaced claims `https://claims.<product-domain>/role` (advisory only) and `https://claims.<product-domain>/auth_strength`, plus Auth0's native `org_id`.
3. The BFF calls the Gateway with an access token for the `main` audience.
4. The Gateway validates the token and resolves the principal (user, org, workspace, role, status) from Valkey and PostgreSQL. **Role, workspace, status and grants always come from the database.** The role claim in the token is only used by the BFF for routing hints; a mismatch with the database denies the request and raises an alert (DEF-09).

No PHI, matter names or patient identifiers may appear in Auth0 profile fields or claims.

### 8.4 Authentication strength: passkeys for the highest-power roles

| Role | Minimum to log in | Required for governance actions and code generation |
| --- | --- | --- |
| Super Admin, co-owner | Passkey login, or password plus a WebAuthn factor | Same, **plus at least two registered phishing-resistant authenticators** (for example a device passkey and a security key), and a fresh authentication within 5 minutes |
| Admin | Same as Super Admin | Same |
| Tenant | WebAuthn or TOTP (organization policy can require passkeys) | Fresh authentication within 5 minutes for exports |

How it is enforced:

- When a person becomes a Super Admin or admin, the identity service sets `app_metadata.privileged = true` through the Management API. The post-login Action reads it and, if the user has no WebAuthn factor, enrolls one; otherwise it challenges with WebAuthn. Because a privileged role is assigned before the first privileged login, the first authorization request after approval is where enrollment happens.
- The Action computes `auth_strength` from the authentication methods Auth0 records for the session: `passkey` (primary login by passkey), `webauthn_mfa` (WebAuthn second factor), `otp_mfa` (TOTP), or `password`. The Gateway rejects a privileged principal whose `auth_strength` is `otp_mfa` or `password`.
- Auth0 keeps login passkeys and MFA WebAuthn credentials in separate credential systems and cannot merge them, so a privileged user may enroll both; either satisfies the policy. The exact method names the Action sees are pinned by a contract test against the real tenant (G2.7) so an Auth0 change fails the build instead of silently weakening the policy.
- Authenticator counts come from the Management API (authentication methods) and are synced by the identity worker; `GET /v1/me` exposes `has_backup_authenticator`. Governance endpoints require it.
- **Recovery never downgrades.** A privileged user who loses every authenticator cannot self-recover with a password and TOTP. Recovery is `owner_recovery` (for a Super Admin) or an admin re-onboarding path with a 72-hour wait, identity verification, and notice to the co-owner and admins.
- Privileged sessions are shorter: idle timeout 15 minutes, absolute limit 8 hours. Tenants: idle 30 minutes, absolute 12 hours. Organizations can tighten both.

### 8.5 Token verification at the Gateway

- Signature checked against the Auth0 JWKS (cached; refreshed on unknown `kid` with a rate limit). Only RS256 is accepted; `none` and HS256 are rejected.
- `iss` must match the tenant domain exactly; `aud` must equal the API identifier (this also rejects ID tokens used as access tokens); `azp` must be an allowed client.
- `exp` and `nbf` are checked with at most 30 seconds of skew.
- `org_id` must be present and must equal the organization of the user's active membership.
- Access tokens live 10 minutes. Refresh tokens rotate with reuse detection.

### 8.6 Suspension and revocation in seconds

A JWT cannot be recalled, so the platform never relies on expiry:

1. The identity service sets the membership state in PostgreSQL and increments `principal_version` in one transaction.
2. It deletes the principal from the shared Valkey cache and publishes an invalidation message. Gateways keep an in-process copy for at most 5 seconds, every shared-cache entry expires within 30 seconds, and if Valkey is unreachable the Gateway reads PostgreSQL directly or denies the request. It never serves a stale principal.
3. It calls the Auth0 Management API to remove the Organization membership or block the user, delete refresh tokens and end sessions, so no new tokens are issued.
4. Open streams are cut by the same invalidation message.

| Objective | Target | Hard bound |
| --- | --- | --- |
| New requests from a suspended user rejected | p99 ≤ 2 s when pub/sub is healthy | 5 s (in-process TTL) when pub/sub is down |
| Open SSE stream cut | ≤ 2 s on the invalidation message | 15 s (periodic status poll) as fallback |

(v2.1 stated 2 s for requests, 5 s for the in-process copy and 15 s for streams without reconciling them, DEF-07. The table above is the single definition; G3.4 measures both rows.)

### 8.7 Step-up authentication

A fresh authentication event (within 5 minutes, and a strength of `passkey` or `webauthn_mfa` for privileged roles) is required to generate or rotate either code, approve or remove an admin, remove a tenant, change policy flags, start break-glass, approve any governance request, or export audit data. The Gateway signals the need with the standard step-up challenge (RFC 9470: HTTP 401 with `WWW-Authenticate: Bearer error="insufficient_user_authentication"` and a `max_age` hint); the BFF then starts a new authorization request with `max_age` and the Action enforces the factor.

### 8.8 Isolating the Auth0 Management API

Only the identity service holds the machine-to-machine credentials, with the minimal scopes above. Because this credential can mint admins, its compromise is the highest-impact event in the identity system. It lives in its own secret, is rotated on a schedule, and network policy allows Management API egress from the identity service only. The identity service raises an alert for any admin or Super Admin role assignment that does not correspond to an approved membership in its own database (reconciliation job, hourly).

### 8.9 SSO and automatic membership

When an organization connects its own identity provider (a hospital's Entra ID, a firm's Okta), Auth0's automatic-membership option stays off; otherwise anyone who can sign in through that provider would become an organization member with no code and no approval. Users who arrive through SSO without a membership land in onboarding like everyone else. Accounts are matched by connection and subject, never by email, and automatic account linking is disabled. For SSO-backed privileged users the organization's identity provider MUST assert phishing-resistant authentication (enforced by the Action reading the authentication context); if it cannot, those users register a WebAuthn factor in Auth0.

### 8.10 Testing identity for real

There is no mock identity provider (DEF-10). Tests use the real `ci` tenant:

- Real sign-up through Universal Login driven by Playwright, using a Chromium virtual WebAuthn authenticator to create and use real passkeys, and real mailboxes on a project-owned domain read over IMAP for verification emails.
- Session-scoped pytest fixtures log in once per role per worker and reuse refresh-token rotation to stay within the `ci` tenant's rate limits.
- A claim-shape snapshot test (G0.7, G2.7) pins the token structure and the method names the Action observes.
- Limits to plan for: Auth0 rate limits on login and Management API calls, and M2M token allowances; the `ci` tenant is sized and monitored for them.

## 9. Internal trust: service identity and context tokens

### 9.1 The context token

The earlier documents say internal calls must never reuse the user's token, yet retrieval must re-check permissions. The context token resolves both.

1. After resolving the principal the Gateway mints a context token for **one** target service: an ES256 JWT valid for 60 seconds at the start of the call, with a single audience, carrying `sub`, `org_id`, `workspace_id`, `role`, `auth_strength`, `scope_hash`, `scope_version`, `pv` (principal version), `request_id` and `jti`. The Gateway reads `scope_hash` and `scope_version` from the `principal_v` view, where database triggers maintain them whenever grants, walls, exceptions, sessions or workspace flags change; it never reads the underlying tables (DEF-49). The Auth0 token is never forwarded.
2. Services verify signature, audience, expiry and issuer against the internal trust bundle, and build their database context from these claims only. Services reject tokens with the wrong audience, an old issue time or a reused `jti` on state-changing calls.
3. **Signing without a per-request KMS call.** v2.1 put the signing key in KMS and signed by API call, which would make every request wait on KMS and would hit KMS signing quotas at load (DEF-26). Instead each Gateway instance generates an in-memory ES256 key pair every hour. A KMS asymmetric key (the "trust root", held in the KMS or an HSM, never exported, rotated every 90 days with overlapping entries) signs a short **signer certificate** binding that public key to the instance's workload identity and a validity of at most one hour. Context tokens carry the certificate reference in their header; services fetch and cache certificates, verify the KMS signature, and consult a deny-list in Valkey. KMS is called once per instance per hour, a compromised pod yields a key that dies within the hour, and revoking a pod is one deny-list entry.
4. Long-running work (ingestion jobs, open streams) compares the `pv` claim with the current value at checkpoints and aborts on a mismatch. The 60-second lifetime applies to the start of a call, not to a stream already running.
5. The Validator signs verdicts with an equivalent KMS-certified ephemeral key (section 11.6).
6. Alert when a token verifies but was minted outside the Gateway's identity, or when certificate issuance spikes.

### 9.2 Service credentials

Each service also has its own credential so the network layer knows **which service** is calling while the context token says **on whose behalf**. A single shared internal key, as in the earlier local plan, would let any compromised container impersonate any user and any service (DEF-10).

| Layer | Local | Production |
| --- | --- | --- |
| Service-to-service authentication | Per-service secret from `.env`, distinct for each service | mTLS client certificates (cert-manager and SPIFFE-style workload identity) |
| Database | One login role per service, non-owner, `NOBYPASSRLS`, created by the init script | Same, with IAM or short-lived credentials |
| Qdrant | Read-only key for `retrieval`; read-write key for `ingestion` | Same; keys in the secret manager |
| Valkey | ACL user per service with key-prefix permissions | Same |
| Object store | Scoped credentials for `ingestion` only | IAM role for `ingestion` with prefix conditions |
| KMS | AWS dev-account roles per service (decrypt only where listed in section 4.2) | IAM roles per service, key policy conditions on encryption context |

### 9.3 Signed job envelope

Background jobs carry an envelope with `org_id`, `workspace_id`, `owner_user_id`, `doc_id`, `doc_version`, `visibility`, an expiry, the `pv` of the enqueuing principal and a signature by the enqueuing service's certified key. The job row is inserted in the **same database transaction** as the document row (the application calls Procrastinate's SQL defer function inside its own transaction; proven by G0.13), so a job cannot exist without its document. Before writing anything the worker verifies the signature and expiry and re-validates against the database that the document, owner and workspace are still active; otherwise it aborts and logs.

### 9.4 The retrieval ledger

`retrieval_records` is written only by `retrieval` (insert-only grant) and read by `generation` and `citation_validator` (select-only grants), all under RLS scoped to the same workspace, and for reads to the same `user_id` that made the request (DEF-63). Each record holds the `request_id`, the principal's `user_id` and `scope_hash`, and one item per chunk: chunk ID, chunk version, content SHA-256, rank, scores, a request-local alias (`chunk_1`, `chunk_2`, …) and whether it was dropped by the trim step. The ledger replaces forwarding chunk sets through the Gateway, gives the validator a record the Gateway cannot alter, and lets audit prove what was retrieved. The model sees only aliases, never global chunk IDs, so it cannot cite an ID it recalls from anywhere else.

## 10. Layered isolation enforcement

### 10.1 The five layers

| Layer | Where | What it does | Boundary? |
| --- | --- | --- | --- |
| L1 | Browser and BFF | Route guards, hidden menus | No, user experience only |
| L2 | Gateway | Token validation, principal resolution, role route allow-list, rate limits and quotas | Yes |
| L3 | Services | Context-token verification; scoped repository objects that cannot run a query without context; no raw queries | Yes |
| L4 | **PostgreSQL** | RLS, composite foreign keys, FORCE policies | **Final authority** |
| L4b | Vector store, object store, Valkey | Mandatory vector filters and scoped keys, object prefixes and encryption, ACLs | Narrowing and defense in depth. **Not** a self-enforcing boundary for the shared vector collection (section 10.5) |
| L5 | Detection | Audit hash chain, anomaly alerts, canary and provenance tests in CI | Detects failures of L2 to L4b |

v2.1 listed the vector database among the layers that are "final authority". Qdrant's own security documentation scopes JWT access by collection and access level, not by payload, so in a shared collection a missing filter is not rejected by Qdrant (DEF-01). Postgres is therefore the single final authority, and retrieval always resolves chunk text from Postgres under RLS (section 10.5).

### 10.2 Partition key per store

| Store | Partition key | Mechanism | Optional silo tier |
| --- | --- | --- | --- |
| PostgreSQL | `org_id`, `workspace_id`, plus owner and matter | FORCE RLS, composite foreign keys | Dedicated database or cluster per organization |
| Qdrant | `workspace_id` as a tenant-indexed payload field (`is_tenant`) | One collection per embedding version; filter built only by `lmqa_vectorstore` from a principal; read-only key for retrieval | **Collection per workspace with a collection-scoped JWT**, which Qdrant itself enforces; or cluster per organization |
| Object storage | `org_{id}/ws_{id}/doc_{id}/v{n}` | Object keys built server-side from database rows, never from client input (a prefix is naming, not a control); presigned URLs of 60 seconds or less; application-level envelope encryption (section 12.3), plus SSE-KMS with the organization key in production | Bucket per organization |
| Valkey | `o:{org}:w:{ws}:…` | ACL user per service, scope-hashed cache keys, TTLs | Separate instance per organization |
| Audit | `org_id` control chain, `workspace_id` chains | `audit_append` function only; public-key sealed payloads | Per-organization WORM bucket |
| LLM provider | Per request | No-retention contract; per-organization provider setting | Self-hosted or VPC model |

### 10.3 PostgreSQL specifics

- **Roles.** Service roles are non-owners with `NOBYPASSRLS`. Every table uses `FORCE ROW LEVEL SECURITY` so even the owner is bound. Migrations run under a separate owner role that no service holds. Dedicated roles exist for `identity`, `gateway` (the `principal_v` view only), `retrieval`, `generation`, `validator`, `ingestion`, `audit_reader`, `reconciler` (column-level SELECT on IDs and index metadata, no text columns), `ops_metadata_ro` and `audit_writer` (EXECUTE on `audit_append` only).
- **Context** is set per transaction with `set_config('app.org_id', …, true)` and the same for workspace, user and role. Transaction-local settings are safe under PgBouncer transaction pooling; session-level settings would leak between requests. The scoped session helper in `lmqa_db` refuses to execute without a context (G1.7 tests this with interleaved sessions on the real pooler).
- **Fail closed.** Policies read the settings as `NULLIF(current_setting('app.org_id', true), '')::uuid` and likewise for the others. A plain `current_setting(..., true)` returns NULL only if the setting was never set on that connection; after any earlier transaction-local `set_config` on a pooled connection it returns an empty string, and casting that to a UUID raises an error instead of matching nothing (DEF-52). With `NULLIF`, an unset context is NULL and no row matches. Every service runs a **boot self-test**: a query with no context must return zero rows, and a query with a context for a different workspace must return zero rows; otherwise the service refuses to start.
- **Policies implement section 5.4 exactly.** Grant, wall, exception and break-glass lookups go through `STABLE` helper functions owned by a non-login `policy_helper` role. Because FORCE binds even owners, each lookup table has an explicit policy `TO policy_helper` limited to read access for the context user; no service role can call the helpers with another user's ID because the helpers take identity only from the transaction context.
- **Connection routing.** Request-path services connect through PgBouncer in transaction mode; the session-state features they must not use (session `SET`, session advisory locks, `LISTEN`/`NOTIFY`, long-lived cursors) are banned by a CI scan of every SQL string in the repository and a boot check. `psycopg` prepared statements are used only with PgBouncer's prepared-statement support (1.21 or later) or disabled. `audit_append` uses transaction-level advisory locks, which pooling allows. Procrastinate workers, the indexer's listener and Alembic migrations connect directly to PostgreSQL and still set the transaction-local context from the job envelope for every transaction (DEF-53).
- **Principal view.** `principal_v` exposes only what the Gateway needs: user ID, organization, workspace, role, states, `principal_version`, `scope_version` and `scope_hash`. It exposes no grants, walls or content.
- **Index plan.** Composite indexes `(workspace_id, user_id, matter_id)` on grants and walls, `(workspace_id, matter_id, visibility, owner_user_id)` on documents and chunks, partial indexes on active exceptions and sessions. Stage 10 measures policy overhead at 10,000 grants per user (section 22).
- **Super Admin policy** is control-plane only (section 5.3). Tenant counts for Manage Admins come from `workspace_usage`, a rollup of numbers maintained by a job.
- **Identity role** covers only control-plane tables. It has no BYPASSRLS and no access to documents, chunks or audit payloads, so compromising it does not expose content.
- **Audit writes** go through a `SECURITY DEFINER` function `audit_append` that computes the hash chain. No service role holds INSERT, UPDATE or DELETE on audit tables.
- **State machines** are enforced by transition tables and triggers (section 6.1).
- **Differential testing.** A pure-Python oracle implements section 5.4. A property-based test generates random organizations, memberships, grants, walls, exceptions and documents, then asserts that every `SELECT` through RLS returns exactly the oracle's answer, and that the vector filter builder produces a filter whose result set is a superset-or-equal of RLS's (G1.4, G5.4).

### 10.4 Behavior when a dependency fails

| Dependency down | Behavior |
| --- | --- |
| Auth0 | Existing sessions continue until their limits; new logins fail; the system fails closed (no anonymous access) |
| Valkey | Gateway reads PostgreSQL directly (no cache); rate limits degrade to a local conservative limit; answer cache bypassed |
| Qdrant | Retrieval returns 503; no fallback to a keyword scan of Postgres |
| KMS | Cached workspace keys keep working for their TTL (at most 15 minutes), then requests fail closed; certificates already issued keep working until they expire |
| PostgreSQL | Everything stops; no read replica serves writes |
| Audit write fails | The stream stops; no unaudited release |
| LLM provider | Query fails with a clear error; no silent switch to another provider unless the organization configured a fallback |
| Validator | No sentence is released; the query fails |

### 10.5 Vector search isolation

What Qdrant provides (verified against Qdrant's security documentation and release notes): granular JWT RBAC that limits tokens by collection and read or write access (and a `value_exists` claim that ties a token's validity to a record), payload indexes including `is_tenant` for co-locating a tenant's vectors, point retrieval by ID that does not accept a payload filter, audit logging from 1.17 and tiered multi-tenancy from 1.16. What it does not provide: row-level enforcement of a payload filter inside a shared collection. The JWT signing secret is also the shared API key, so any holder of that key can mint any token.

Design consequences:

- **Pooled default.** One shared collection per embedding version. `lmqa_vectorstore` is the only code that can reach Qdrant; its query functions require a principal, build the filter themselves and have no unfiltered variant. Delete-by-filter and payload-update calls also require the workspace filter, and point lookups by ID are never used with user-supplied IDs.
- **Postgres cross-check.** Qdrant returns chunk IDs only. Retrieval fetches chunk text from PostgreSQL by ID under RLS. An ID that Postgres refuses to return means either a stale index or a filter bug; it is dropped, counted in a mismatch metric and, if the reconciler's integrity job finds the ID belongs to a different scope, raised as a high-severity alert.
- **High-assurance tier.** Organizations that require the vector store itself to enforce isolation get one collection per workspace with a collection-scoped JWT minted by a small vector-access broker. The cost is operational (many collections) and it is offered as the silo option (D16).
- **Alternative evaluated.** `pgvector` would put vectors under the same RLS as everything else and remove this whole class of problem. It is rejected as the default because filtered approximate search at tens of millions of vectors per workspace is the Stage 10 risk, but it remains the fallback if load tests show the filtering wrapper and over-fetch path cannot meet the budgets (ADR 0004, DEF-47).
- **Vectors and sparse terms leak.** Embeddings can leak source content through inversion research, and the sparse index exposes terms. The vector database is a sensitive store: private network, encrypted disk, scoped keys, explicit deletion of vectors on document, workspace or organization removal. Keyword search cannot run over ciphertext, so protection is access control. The embedding provider is a data boundary too: sending PHI or privileged text to a third-party embedding API needs the same no-retention contract as the LLM, and sensitive organizations use a self-hosted embedding model.
- **Filter construction.** `org_id` and `workspace_id` always. Tenants: `(owner = me) OR (visibility = matter AND matter_id IN allowed AND tier ≤ max)` with `must_not` on walled matters. Admins: `(owner = me) OR visibility = matter`, plus private documents only when the flag and an active break-glass session allow it. Emergency exceptions add the exception's matter. If no filter can be built the answer is a 403, never an unfiltered search.
- **Very large grant sets.** A tenant with more than 256 granted matters would produce a large filter. Admins never need a matter list. For such tenants retrieval switches to **over-fetch and cross-check**: filter by workspace and visibility only, fetch up to 500 candidates, let PostgreSQL RLS discard disallowed ones, and widen up to a cap if fewer than needed survive. Because Postgres is the authority this is safe, and Stage 10 measures its latency (section 22).

### 10.6 Index consistency: PostgreSQL is the authority

When a document's visibility, matter, tier or owner changes, the vector payload lags. The rule: **PostgreSQL decides; the vector index follows.**

```mermaid
flowchart LR
  CH["Change in PostgreSQL:<br/>visibility, matter, tier, owner,<br/>delete"] --> TX["Same transaction writes<br/>index_outbox row"]
  TX --> IX["indexer worker"]
  IX -- "set payload / delete points" --> QD[("Qdrant")]
  IX --> ST["index_state = in_sync"]
  RC["reconciler job<br/>nightly and on demand"] -- "compare payload version" --> QD
  RC -- "compare chunk ids and versions" --> PG[("PostgreSQL")]
  RC -- "missing: re-upsert<br/>orphan: delete after grace<br/>mismatch scope: alert" --> QD
```

- The change and the `index_outbox` row are written in one transaction. The `indexer` applies payload updates or deletions and marks `index_state = in_sync`; failures retry with backoff and alert when the oldest pending item exceeds 60 seconds.
- **While `stale`, nothing leaks.** If access was narrowed, the vector payload still says "visible" but PostgreSQL RLS refuses the chunk, so it is dropped and counted. If access was widened, the document is simply not retrievable yet; this is the safe direction.
- **Reconciler.** Nightly and on demand, per workspace: compare every chunk's `payload_version` and ID in Qdrant with PostgreSQL's chunk list and index versions. Missing vectors are re-upserted (re-embedding if needed), orphan vectors (no Postgres chunk) are deleted after a 24-hour grace period, and any vector whose scope fields disagree with PostgreSQL is corrected and raised as an alert, since it could mean a filter or ingestion bug.
- **Chunks are immutable per document version.** A re-ingest creates a new version; searchable payloads carry `is_current`. Old chunk versions remain readable by audit under legal hold so a past citation can always be resolved.
- Document deletion destroys the document key (section 12.9), then the outbox deletes vectors and objects. The reconciler verifies that no vector remains for a deleted document.

### 10.7 Semantic cache

The earlier design matched near-duplicate queries "against the same document set" and let a hit skip retrieval, which also skips the access filter (DEF-06). v3.0 moves the cache **after** retrieval:

- The cache lives in `generation`. Retrieval always runs (it is cheap and always filtered); the cache saves the expensive LLM call.
- Key = hash of `org_id`, `workspace_id`, `scope_hash`, the hash of the retrieved chunk set (IDs and versions), `prompt_version`, model identifier, and the normalized query. Near-duplicate matching by query-embedding similarity is allowed only inside one such bucket.
- Because retrieval already produced only visible chunks, a hit cannot reveal anything the caller could not already retrieve. The validator still re-checks every cached answer against the current ledger, so permission or document changes cannot make a stale answer pass.
- Entries are encrypted with the workspace cache key (rotated daily so entries expire naturally) and live at most one hour. Cached answers contain PHI, which the original design says Redis should not hold, so caching is **off by default for medical organizations** and opt-in (D12). Entries are never shared across workspaces.

### 10.8 Async ingestion and fairness

Jobs carry the signed envelope (section 9.3). Queues are fair-share per workspace: each workspace has N job-lock slots (`ws:{id}:slot:{k}`, N = its concurrency cap), so a single lock never serializes a whole workspace and one admin's 5,000-page upload cannot starve others. Uploads use presigned PUT URLs constrained to the workspace prefix, size, content type and required SHA-256 checksum. Files are scanned and type-verified before OCR or parsing. Identical files, chunks and embeddings are never deduplicated or cached across workspaces, because deduplication would reveal that another workspace holds the same document (G4.9).

### 10.9 LLM and prompt layer

Only chunks that passed the filters reach the prompt, so the model cannot disclose what it never receives. The residual risk is a document shared to a matter that contains injected instructions. Controls: delimited chunk blocks with an explicit instruction hierarchy, request-local aliases instead of global IDs, no tools or network access for the generation model, the citation validator, and output sanitizing in the viewer. Prompts and completions are logged only into the organization-scoped, sealed audit payload.

### 10.10 Pooled by default, siloed when required

A small `OrgRouter` in `lmqa_db` maps `org_id` to its connection set (database DSN, vector collection or cluster, bucket, KMS key). Pooled infrastructure is the default mapping; a hospital system that requires physical separation gets a different mapping through the same interface. Database-per-organization is not the default because migrations and pools across hundreds of databases are costly; pooled storage with RLS and a key per organization delivers most of the isolation.

## 11. The RAG pipeline

### 11.1 Ingestion

Document lifecycle API and workers live in `ingestion`. The Gateway only routes; it never holds object-store credentials or presigns URLs (v2.1 had the Gateway minting presigned URLs, which contradicted "the Gateway holds no business logic and no storage credentials", DEF-23).

| Step | What happens | Failure handling |
| --- | --- | --- |
| 1. Upload init | `POST /v1/documents/uploads`: quota check, tier-ceiling check, `documents` row in `uploading`, presigned PUT to the **quarantine prefix** bound to workspace, size, content type and a required SHA-256 checksum | Reject with a uniform error; nothing stored |
| 2. Complete | `POST /v1/documents/{id}/complete`: verify the object exists and the checksum matches; state `scanning`; enqueue the job in the same transaction | Checksum mismatch deletes the object and marks `failed` |
| 3. Scan | ClamAV, file-type verification (magic bytes against declared type), size, page and decompression-bomb limits, removal of PDF active content (JavaScript, embedded files, launch actions) | Infected or malformed files are deleted and the document is `failed` with a reason code |
| 4. Parse | Structured sources first: JATS XML, SPL (drug label) XML, DOCX, sanitized HTML. Otherwise PDF: use the text layer where present; pages with no usable text layer go to OCR. The extraction mode is recorded per page | Parser crash isolates to a sandboxed worker process; retry once, then `failed` |
| 5. OCR | Tesseract with per-word confidence. Page confidence = length-weighted mean of word confidences plus the share of low-confidence words. Default threshold 0.85 per page, configurable per organization | Pages below the threshold create **quarantined** chunks and the document enters `ocr_review` |
| 6. Structure detection | Layout analysis plus rules. Legal: ARTICLE, Section, Clause numbering, schedules and exhibits, defined-term sections. Medical: SOAP headers (Subjective, Objective, Assessment, Plan), HPI, medication lists, encounter boundaries, LOINC section codes in drug labels, JATS section titles | If detection finds no structure the chunker falls back to paragraph chunks and records `structure = fallback`, which the library shows as a warning (never silent) |
| 7. Chunk build | Chunks by structural unit, **including a preamble chunk** for text before the first heading (parties, recitals, effective date) and table chunks that keep rows together. Token targets: minimum 40, target 300 to 700, maximum 1,200. A unit longer than the maximum is split on paragraph boundaries with about 10 percent overlap, recorded in metadata | Overlong or empty chunks fail validation tests (G4.2) |
| 8. Encrypt and store | A per-document key (wrapped by the workspace key) encrypts chunk text (AES-256-GCM with associated data binding org, workspace, document, version and chunk ordinal). The original file is re-encrypted into the final prefix and the quarantine object is deleted | A failed write leaves the document `failed`; no partial chunk set is searchable |
| 9. Index | The `indexer` reads chunks, embeds them (dense plus sparse), upserts to Qdrant and marks `index_state = in_sync`. **Quarantined chunks are never embedded** | Retries with backoff; alert if pending more than 60 seconds |
| 10. Complete | Document `indexed`; owner notified | Dead-letter queue with alert for poison jobs |

The deep-dive sketch flagged low-confidence pages for review but then embedded every chunk anyway, and it dropped text before the first section; both are corrected here (DEF-33, DEF-34).

**OCR review.** The owner or admin sees the page image beside the extracted text, corrects or approves each quarantined page, and the correction creates a new document version with `text_source = human_corrected` and offsets preserved. Review queue depth is a staffed metric: the review step cannot silently become the bottleneck.

### 11.2 Chunk model and citations

| Field | Purpose |
| --- | --- |
| `chunk_id`, `doc_id`, `doc_version`, `ordinal` | Immutable identity; chunks never change after creation |
| `org_id`, `workspace_id`, `owner_user_id`, `matter_id`, `visibility`, `confidentiality_tier` | Access fields; written to every vector payload |
| `privilege` (none, attorney-client, work product), `contains_phi` | Compliance tags used by policy and export controls |
| `kind` | `preamble`, `clause`, `section`, `soap_subjective`, `soap_objective`, `soap_assessment`, `soap_plan`, `paragraph`, `table`, `footnote` |
| `section_path`, `clause_no`, `heading` | What a lawyer or clinician actually verifies against |
| `page_start`, `page_end`, `spans[]` (page, character start and end, bounding boxes) | Multi-page units cite correctly; spans drive the highlight in the side panel (the sketch stored only the first page) |
| `text_ciphertext`, `text_sha256`, `token_count`, `ocr_confidence_min`, `ocr_confidence_mean`, `quarantined`, `text_source` | Integrity and review state |
| `effective_date`, `is_current`, `payload_version` | Version selection and index consistency |

A **citation** shown to the user resolves a request-local alias through the ledger to: document title and version, page range, section path or clause number, and the highlighted span inside the chunk. The side panel re-checks visibility under RLS when opened, so a permission change after the answer was produced still applies.

### 11.3 Retrieval

1. Verify the context token; open a transaction with context; resolve the **scope** from the database (allowed matters with tier ceilings, walls, active exceptions and sessions, workspace flags). Cache the scope under `scope_hash` and `scope_version` for at most 30 seconds and invalidate on any change.
2. Build the vector filter (section 10.5) and run a Qdrant hybrid query: dense and sparse prefetch of 100 candidates each, fused with reciprocal rank fusion, in one request. Hybrid search matters because legal and medical queries contain exact terms (statute numbers, drug names, dosages) that dense search alone misses.
3. Fetch the candidates' chunk text from PostgreSQL under RLS and decrypt. Any ID that does not come back is dropped and counted (section 10.5).
4. Cross-encoder re-ranking of the surviving candidates. Keep at most 12 chunks at or above the calibrated relevance threshold; the rest are recorded as dropped with their score.
5. Write the **retrieval record** (section 9.4) in the same transaction and return `request_id` and counts to the Gateway.

Defaults are starting values to be tuned by the evaluation harness: prefetch 100 + 100, keep 12, context budget 12,000 tokens, maximum output 1,500 tokens. Evaluation floors are recorded in `eval/floors.toml` and may only be lowered by an ADR.

### 11.4 Token optimization

For documents of 50 to 200+ pages `generation` enforces a hard per-request budget before any LLM call:

1. **Count before sending** using the provider's own tokenizer or token-count endpoint (for example `tiktoken` only for model families that use it). The gate compares the count with the provider's reported usage and requires agreement within 1 percent (G6.1).
2. **Trim by relevance, not truncation.** Chunks below the relevance threshold are dropped whole.
3. **Compress what is kept**, but guarded: prompt compression (LLMLingua-2 style) is applied only to verbose prose chunks, never to tables, and it MUST preserve every critical token (numbers, dates, currency amounts, dosages with units, statute and section references, defined terms). A compression that drops one is discarded and the uncompressed chunk is used or dropped. The validator always checks against the **original** chunk text, never the compressed text (G6.3).
4. **Semantic caching** per section 10.7.
5. **Context reordering:** the most relevant chunks go at the start and end of the prompt, not the middle.

Every request records tokens in and out and the chunks dropped by the trim step with reasons, so audit can answer whether a relevant passage was excluded for budget reasons.

### 11.5 Prompt and citation protocol

- **System prompt** (versioned in `prompts/templates/`): output format fixed; every factual sentence ends with one or more tags `[chunk_N]`; the canonical refusal sentence is "The provided documents do not address this."; text inside chunk blocks is untrusted data and never instructions.
- **Chunk injection:** `<chunk alias="chunk_3" doc="Smith_Contract.pdf" page="12-13" section="4.2">…</chunk>`. Aliases are request-local and mapped to chunk IDs by the ledger. The model never sees or produces global chunk IDs.
- **Citation list:** the earlier design asked the model to end with a structured citation list. The model can get that list wrong, so v3.0 drops it from the model's task: the **validator builds the citation list deterministically** from the tags in the validated sentences (DEF-35).
- **Few-shot examples** (`prompts/few_shot_examples/`): correct citation format for single-chunk and multi-chunk sentences, and at least one correct refusal. The evaluation set tests that the refusal example generalizes.
- **Versioning:** every prompt version has a content hash. The hash, model identifier and provider settings are recorded in the audit payload of every query.

### 11.6 Citation validation and gated delivery

**Delivery modes** (organization policy):

| Mode | When | Behavior |
| --- | --- | --- |
| `sentence_gated` (default) | `on_fail = strip` | The Gateway forwards the generation stream to the Validator. The Validator segments it into sentences (one pinned segmenter), validates each completed sentence and returns a signed verdict that carries the sentence text; the Gateway releases only sentences with a passing verdict. First visible text appears after the first sentence validates |
| `buffered` | Required when `on_fail = regenerate` | The whole answer is generated and validated before anything is released; on failure the answer is regenerated (at most 2 attempts), then the query fails with a clear message |

v2.1 and the earlier documents let raw tokens stream to the browser and "marked them unverified until the validator result arrives". That contradicts "every citation is machine-validated before the answer reaches the user" and cannot work with regeneration (DEF-05). The "provisional" mode is removed; there is no mode in which unverified text is shown.

**Validator checks (all deterministic; no generative LLM):**

| Check | Rule |
| --- | --- |
| V1 Tag grammar | Tags match `[chunk_N]` exactly; malformed tags fail the sentence |
| V2 Alias membership | Every alias exists in this request's ledger |
| V3 Chunk integrity | The current chunk's content hash equals the ledger hash; a changed chunk fails the sentence |
| V4 Citation required | Every sentence except headings and the canonical refusal carries at least one tag; an uncited factual sentence fails |
| V5 Critical-token match | Every number, date, amount, dosage with unit, and statute or section reference in the sentence appears in the cited chunk text after normalization (units, thousands separators, date formats) |
| V6 Entailment | A pinned NLI cross-encoder scores the sentence against the cited chunks' relevant windows; the score must reach the calibrated threshold (multi-chunk sentences use the concatenation of the cited windows) |
| V7 Refusal consistency | A refusal sentence uses the exact canonical wording, carries no tags and makes no other claim in the same sentence. A partial answer (supported sentences followed by a refusal about the unanswered part) is allowed. If every content sentence of an answer fails, the answer is replaced by the canonical refusal |
| V8 Resolution | Each tag resolves to document, page range, section and highlighted span |

"Deterministic" means: the same input yields the same verdict on every run and after every restart. The NLI model is pinned by weights hash, runs on CPU with fixed batch size and thresholds, and a determinism test runs each case twice across a process restart (G7.4). The thresholds are calibrated on human-labeled real data so that sentences judged "supported" have precision of at least 0.99 on a held-out set; the floor lives in `eval/floors.toml`.

**Outcomes** per organization policy `on_fail`: `strip` replaces the failing sentence with a visible marker ("A claim in this answer could not be verified and was removed", with a reason code), `regenerate` retries as above, and a final `refuse` states that no verified answer could be produced. Every verdict is logged.

**Signed verdicts and write-ahead audit.** The Validator returns, for each sentence, a verdict signed with its KMS-certified ephemeral key over (`request_id`, sentence SHA-256, verdict, check results). Before the Gateway sends any sentence it appends a `segment.released` audit event (hashes only). At the end it appends `query.completed` with the sealed payload (question, chunk references, full answer, verdicts, prompt hash, tokens, dropped chunks). If any audit write fails the stream stops. The final audit event stores the hash of the released text and the verdict signatures, so a reviewer can prove that what the user saw is what the validator approved.

**Stream protocol** (SSE, designed for resumption): events `status` (retrieving, generating, validating), `sentence` (text, citation aliases, event ID), `citations` (resolved list), `warning`, `done`, `error`. Released sentences are also kept for 10 minutes in an encrypted, workspace-scoped resume buffer in Valkey keyed by `request_id`; a client that reconnects with `Last-Event-ID` receives only sentences from that buffer, which were already released and audited (DEF-62).

**What the validator cannot catch.** A chunk that is itself wrong, an entailment error on a subtle negation, and claims that no sentence-level check can see. The calibration floor limits the rate, the human-review workflow and the disclaimer cover the rest, and the evaluation harness measures both (G7.3).

### 11.7 Prompt and model lifecycle

Templates live in `prompts/` in the repository, versioned by content hash and promoted only when the evaluation harness (held-out real questions with known citations) shows the citation-validation pass rate, refusal accuracy and retrieval metrics at or above `eval/floors.toml`. Self-hosted Langfuse may be used for traces and A/B analysis; the repository is the source of truth. Canary deployment of prompt or model changes is evaluated against the live validation pass rate before full rollout (Stage 11).

### 11.8 LLM and embedding provider boundary

The provider is chosen per organization (D17). Medical organizations default to a provider under a BAA with no-retention terms, or a VPC-isolated or self-hosted model; legal organizations default to a no-retention contract. The `llm_client` interface is provider-agnostic, supports streaming, timeouts, idempotent retries and per-organization keys and budgets. Open question carried from the earlier review comment: whether self-hosting should be the default instead of the exception. The recommended answer is: provider API with BAA and no retention for the pilot, self-hosted option built and tested by Stage 11, and the choice recorded per organization.

## 12. Encryption and key management

### 12.1 Key hierarchy

```mermaid
flowchart TD
  CMK["Organization CMK in KMS<br/>multi-Region replica, deletion guards"]
  ESC["Escrow CMK<br/>separate vault account, separate admins"]
  WCK["Workspace content key<br/>random 256-bit, stored wrapped"]
  AUK["Audit key pair per workspace per month<br/>public key seals, private key wrapped"]
  OCK["Organization control key<br/>contact fields, control-plane fields"]
  DK["Document key<br/>one per document, wrapped by workspace key"]
  CAK["Cache key<br/>rotated daily"]
  CT["Chunk ciphertext and stored object"]
  CMK --> WCK
  CMK --> AUK
  CMK --> OCK
  WCK --> DK
  WCK --> CAK
  DK --> CT
  WCK -. "escrow copy" .-> ESC
  OCK -. "escrow copy" .-> ESC
  AUK -. "escrow copy" .-> ESC
```

| Key | Type and scope | Wrapped by | Used by | Destroyed when |
| --- | --- | --- | --- | --- |
| Organization CMK | KMS symmetric key, one per organization, multi-Region primary plus replica | n/a (held in KMS) | Wrapping and unwrapping the keys below only | Organization destruction ritual (section 12.7) |
| Workspace content key | Random 256-bit key per workspace, versioned | Organization CMK | Wraps document keys and cache keys | Workspace destruction |
| Document key | Random 256-bit key per document | Workspace content key | Encrypts that document's chunk text and stored object | Document deletion (crypto-erase) |
| Audit key pair | X25519 key pair per workspace per calendar month | Private key wrapped by the CMK; public key stored in clear | Writers seal payloads with the public key; only the `audit` service unwraps the private key | End of that month's retention period |
| Organization control key | Random 256-bit key per organization | Organization CMK | Encrypts contact fields and sealed control-plane reasons | Organization destruction |
| Cache key | Random key per workspace, rotated daily | Workspace content key | Encrypts cached answers | Daily rotation (entries expire with it) |
| Blind-index key | Random key per organization | Organization control key | HMAC blind indexes for equality lookup (email) | Organization destruction |
| Code pepper | Secret in the secret manager, versioned | n/a | Keyed hashing of join codes | Rotation |
| Context-token trust root | KMS asymmetric key (ECC P-256), sign and verify only | n/a | Signs short-lived signer certificates (section 9.1) | Rotated every 90 days with overlap |

v2.1 derived workspace and audit sub-keys from one data key with HKDF. A derived key cannot be destroyed on its own (the parent can re-derive it), so "destroy content without touching audit retention" and per-workspace crypto-shredding were not achievable (DEF-03). Independent random keys, each wrapped, fix that.

### 12.2 What is encrypted

- **Column level:** document titles, chunk text, questions, answers, audit payloads, user contact fields, and reason text. AES-256-GCM with associated data binding `org_id`, `workspace_id`, object ID and version, so ciphertext copied into another row or workspace fails to decrypt.
- **Objects:** application-level envelope encryption (section 12.3), plus SSE-KMS with the organization CMK in production.
- **Disk and backups:** encrypted at rest beneath all of the above.
- **Equality lookups** (email, code lookup ID) use HMAC blind indexes.
- **Keyword and vector search cannot run over ciphertext**, so the vector database is protected by access control (section 10.5).

What this protects: storage, backup and snapshot breaches, and provable deletion. What it does not protect: an application bug that unwraps the wrong key, which is the job of RLS and scoped filters, and a compromise of a running service that legitimately holds keys in memory.

### 12.3 Object encryption

MinIO's server-side encryption hooks and the S3 SSE-KMS encryption context are not available identically in every S3-compatible local store, and the community edition of MinIO is in maintenance mode (section 4.5). Encryption is therefore done by the application, which gives identical behavior locally and in production and keeps plaintext out of the store:

1. Uploads land in the **quarantine prefix** (SSE-KMS in production, 24-hour lifecycle expiry; plaintext locally, acceptable because local data is public documents only, R4).
2. After scanning and parsing, the worker streams the file through chunked AES-GCM (1 MiB segments, per-segment nonces, a final-segment marker so truncation is detected) under the document key and writes it to the final prefix; then deletes the quarantine object.
3. Downloads are decrypted and streamed by `ingestion` through the Gateway. The browser never receives a URL to ciphertext; presigned URLs exist only for uploads to the quarantine prefix.

### 12.4 Rotation

- **CMK:** provider automatic rotation of key material (no data rewrite, no re-wrap).
- **Workspace content key:** a new version for new documents; old versions stay readable; documents are re-wrapped lazily. Document keys do not change.
- **Emergency rotation:** a runbook re-wraps a workspace's document keys under a fresh workspace key and, if the CMK is suspected compromised, creates a new CMK and re-wraps every key row for the organization.
- **Trust root:** every 90 days, with overlapping certificates; services trust both during the overlap.

### 12.5 Deletion guardrails

The per-organization key that makes shredding possible also makes one accidental or malicious deletion permanent. Four layers, plus an asymmetry rule, defend against it. Even *scheduling* deletion makes a key unusable while it is pending, so scheduling is an availability attack as well as a data-loss risk.

| Layer | Control |
| --- | --- |
| Preventive (cloud policy) | An organization-wide service control policy and the key policies explicitly deny `kms:ScheduleKeyDeletion`, `kms:DisableKey`, `kms:PutKeyPolicy` and `kms:DeleteImportedKeyMaterial` for every principal except two roles: `keyguard-destroyer` (may schedule deletion or disable) and `key-admin` (may change policy, with MFA and a change ticket). `keyguard-destroyer` can be assumed only by the KeyGuard workflow, which attaches session tags carrying two distinct approval IDs that the key policy checks. Service roles have only `Encrypt`, `Decrypt`, `GenerateDataKey` and `ReEncrypt` with encryption-context conditions; key administrators have no cryptographic use |
| Preventive (waiting window) | The provider's waiting period is always the maximum (30 days for AWS KMS) for every non-drill key. A policy lint in CI fails if any production key has a shorter window. Multi-Region primaries with replicas cannot complete deletion until the replicas are deleted, which adds a second hold (verify at pin) |
| Preventive (platform) | `org_keys.deletion_protection` stays true. KeyGuard refuses to call any destroy operation unless the organization is `sealed`, an `executable` governance request has the required distinct approvers, the waiting window has elapsed, retention has ended and no legal hold exists |
| Detective | Every `ScheduleKeyDeletion`, `DisableKey`, `CancelKeyDeletion`, `PutKeyPolicy` and key-material event raises a page to security on-call within 60 seconds. An automated responder compares the event with KeyGuard's approved records; if none matches it cancels the deletion and re-enables the key. The responder role can only cancel and enable |
| Asymmetry | Restoring is easy and fast: cancelling a scheduled deletion and re-enabling the key needs one person or the automated responder. Destroying is hard: two people, passkey step-up and a window |

### 12.6 Two-person approval, windows and sealing

| Operation | Approvers (distinct humans, passkey step-up within 5 minutes of each approval) | Wait |
| --- | --- | --- |
| Unseal a workspace | Super Admin (or co-owner) plus operator `key_custodian` | 72 h |
| Destroy a workspace's keys | Super Admin (or co-owner) plus operator `key_custodian`; retention ended; no legal hold | 30 days after approval |
| Delete an organization | Co-owner or a signatory verified out of band by an operator, plus `key_custodian` at the key stage | 30-day grace plus the provider window (at least 60 days in total) |
| Platform-initiated destruction (for example contract termination) | Authorized customer signatory verified by `security_officer`, plus two `key_custodian` operators | 30-day grace plus the provider window |

Approvals expire after 72 hours if not completed. Approvers cannot be the initiator, and a human who holds two identities is flagged by the owner-linked rules (section 5.9).

**Sealing.** Every workspace content key already has an escrow copy wrapped under the organization's **escrow CMK** in the vault account (section 12.8), whose key policy requires two custodian principals to use it. When a workspace becomes `sealed`, the CMK-wrapped copy in the database is removed, so services can no longer unwrap the key; unsealing means two custodians release the escrow copy and it is re-wrapped under the organization CMK. There is no separate "seal key" (DEF-56). "Unreadable by anyone" is therefore a property of the key setup, not only of a status flag.

### 12.7 The organization destruction ritual

```mermaid
flowchart TD
  R0["R0  Super Admin starts org_delete<br/>passkey step-up, no legal hold,<br/>retention check or attestation"] --> R1["R1  Second approver approves<br/>co-owner or verified signatory, passkey"]
  R1 --> R2["R2  deletion_pending for 30 days<br/>export window, workspaces frozen,<br/>notice to all admins"]
  R2 -- "cancel, one person" --> OK["Organization active again"]
  R2 --> R4["R4  sealed: content keys disabled,<br/>custodian approves key stage,<br/>replica deleted first, then CMK and<br/>escrow key scheduled together, 30 days"]
  R4 -- "restore: cancel deletion,<br/>re-enable key, one person plus custodian" --> FR["frozen, then operator release"]
  R4 --> R6["R6  provider windows end:<br/>CMK and escrow key deleted,<br/>vectors and objects deleted,<br/>Auth0 Organization removed"]
  R6 --> R7["R7  destruction record signed by<br/>custodian and security officer,<br/>tombstone ledger entry"]
  R7 --> R8["R8  verification: decrypt fails,<br/>no vector or object remains,<br/>restore replays tombstone"]
```

The minimum elapsed time from request to irreversible destruction is 60 days. The drill version runs in a throwaway organization whose keys carry a `drill` tag that the policy lint allows to use the provider's 7-day minimum window, so the full path including the real KMS deletion is exercised annually (G9.6).

### 12.8 Backup, disaster recovery and escrow

- **Replica:** each organization CMK is a multi-Region primary with a replica in the DR Region, so a regional failure does not strand data.
- **Escrow:** wrapped copies of workspace, control and audit keys are also written under an **escrow CMK** in a separate vault account with separate administrators and no day-to-day access. If the primary account, the CMK and the replica were all lost or maliciously deleted, escrow still allows recovery. Escrow keys are per organization so organization destruction can destroy them too.
- **Data backups:** PostgreSQL point-in-time recovery, Qdrant snapshots, object versioning, and hourly Merkle anchors in an Object Lock bucket, all copied cross-Region. Backups contain only ciphertext and wrapped keys, so they are unreadable without the CMK.
- **Customer-held keys:** if an organization brings its own key, loss of that key by the customer is loss of data by design; the contract says so.
- **Drills:** quarterly restore from escrow into an isolated account; annual full destroy drill; annual restore-and-shred drill that proves a shredded organization stays unreadable in a restored backup.

### 12.9 Shredding semantics and backups

| Deletion scope | What is destroyed | Effect in live systems | Effect on backups |
| --- | --- | --- | --- |
| One document | Its document key | Chunk text and object unrecoverable at once; vectors and objects deleted by the outbox | The wrapped key still exists in older backups until they expire (maximum 35 days) |
| One workspace | Workspace content key, all document keys, audit keys at the end of their retention | Same | Same, plus the **tombstone ledger** |
| One organization | The CMK and escrow keys | Everything unreadable immediately after the provider window | Unreadable forever, because every wrapped key in every backup depends on the destroyed CMK |

v2.1 claimed that per-organization keys make restored backups unreadable for any deletion. That is true only at organization level: a backup of the wrapped-key table taken while the organization's CMK still exists can unwrap a deleted document's key (DEF-04). The fix is a **tombstone ledger** kept outside the backup set (an Object Lock bucket in the vault account) that records every document, workspace and tenant deletion. Any restore replays the ledger before the restored system accepts traffic, and restores are per organization. Backups expire within 35 days, which bounds the window.

### 12.10 Local mode and repository hygiene

- Key provider interface with two real adapters: AWS KMS (dev account) and OpenBao Transit. OpenBao allows immediate deletion for the tests that must prove shredding; AWS KMS is used for everything that depends on its real behavior (policies, windows, signing). A file-backed fake is **not** used (DEF-10).
- `.gitignore` in the first commit ignores `.env`, `.env.*`, `.secrets/`, `*.pem`, `*.key` with an explicit `!.env.example` (a bare `.env*` pattern also hides the template). gitleaks runs as a pre-commit hook and a CI check; peppers and signing keys never appear in `compose.yaml`.

## 13. Audit, alerting, quotas and compliance mapping

### 13.1 Event model

Every action writes two records:

- **`audit_event` (metadata):** ID, timestamp, `org_id`, `workspace_id`, actor, actor role, action, target (IDs only), outcome, reason code, request ID, IP, user agent, scope (org, workspace or tenant), `prev_hash`, `hash`.
- **`audit_payload` (content):** question text, retrieved chunk references, answer, verdicts, dropped chunks, token counts, prompt hash, sealed under the workspace-month audit key.

The split lets a Super Admin or an operator review events about admins without ever reading content.

### 13.2 Sealed payloads

v2.1 encrypted audit payloads with a symmetric key that every writer needed, so every service could read every audit payload (DEF-27). Payloads are now **sealed to a public key** (HPKE): writers hold only the public key and can encrypt but not decrypt. Only the `audit` service unwraps the month's private key (a KMS decrypt call gated by its role) to serve reads. The hash of the ciphertext is part of the chain, so shredding a month's key does not break verification.

### 13.3 Chains, anchoring and retention

- **Chains:** one hash chain per workspace and one control-plane chain per organization, not one per organization, because a single chain would serialize every audit write. `audit_append` takes a per-chain transaction-level advisory lock (safe under connection pooling) and computes `hash = H(prev_hash + canonical event)`. If Stage 10 shows the lock limits throughput, a workspace chain is split into N shards by user hash, each independently verifiable, with the Merkle root covering all shard heads.
- **Anchoring:** an hourly Merkle root over all chain heads is written to an Object Lock bucket in compliance mode and verified by a scheduled job.
- **Immutability:** services have no direct write access to audit tables, a trigger rejects UPDATE and DELETE, and tables are partitioned by month.
- **Retention without breaking the chain.** Dropping or archiving an old partition would break chain verification across the gap (DEF-16). Before a partition is detached, a **checkpoint record** with the last hash of the range is written to the chain and anchored, and the verifier treats a checkpoint as a valid chain start.
- **Release evidence:** `segment.released` events (hashes only) are written before each sentence leaves the system, and `query.completed` carries the sealed payload (section 11.6).

### 13.4 What is recorded

| Category | Examples |
| --- | --- |
| Identity | Login, MFA failure, token rejected, step-up, authenticator changes |
| Onboarding | Code verification (success and the true failure reason), membership created, approved, rejected |
| Governance | Code rotated, state or policy change, governance request steps, wall created or lifted, break-glass and emergency sessions, successor transfer, key operations |
| Data | Upload, delete, grant change, visibility change, full query chain, export, downloads |
| System | Validation outcome, cache hit, tokens dropped, quota hit, vector-versus-Postgres mismatch, reconciler repairs |
| Operators | Every JIT grant, session, and action (written to the organization's audit view too) |

### 13.5 Who can read what

| Viewer | Events | Payloads |
| --- | --- | --- |
| Super Admin | Org-level and admin-level events; tenant activity as aggregate counts only | Never |
| Admin | Whole workspace | Per workspace policy |
| Tenant | Own history, including break-glass sessions that touched their documents | Own |
| Platform operator | Infrastructure events only | Never (content access needs the workspace admin's approval; control-plane data needs the Super Admin's; always audited) |

### 13.6 Detection signals and alerts

v2.1 alerted on "any RLS denial". PostgreSQL row-level security silently filters rows on SELECT and raises an error only for write-side policy violations, so most denials are invisible to the application (DEF-08). Detection is therefore built from signals that actually exist:

| Signal | Source | Severity |
| --- | --- | --- |
| Write rejected by a policy (SQLSTATE 42501) | PostgreSQL | High |
| Vector hit that Postgres refused to return | Retrieval mismatch metric | Medium; high if the reconciler finds the vector belongs to another scope |
| Resource ID requested outside caller's scope (404) | Gateway | Low individually; high on bursts or enumeration patterns |
| Boot self-test failure, FORCE-RLS or role-attribute drift | Service start, nightly schema audit | High |
| Canary and provenance tests in CI or production probes | Test harness | Page |
| Burst of failed code attempts; Organization Code used from a new country; one user in two countries at once | Identity | Medium to high |
| Admin or Super Admin role assigned outside an approved membership | Reconciliation job | High |
| Admin pending approval beyond N days; approval followed by bulk tenant creation | Identity | Medium |
| Any break-glass, emergency or operator session; unreviewed emergency access at 48 and 72 hours | Access sessions | High (page for operators) |
| Failed audit-chain or anchor verification | `audit` | High |
| KMS scheduled-deletion, disable, key-policy events; unusual KMS call volume | CloudTrail | Page within 60 seconds |
| Token verified but minted outside the Gateway identity; certificate issuance spike | Internal trust | High |
| Unusual token spend per workspace; quota at 80 percent | Quotas | Medium |

Every alert has a drill test that triggers it for real and checks delivery to a real on-call channel (G9.3).

### 13.7 Quotas and noisy-neighbor control

Budgets are hierarchical: organization plan limits (admins, tenants per admin, storage, ingestion pages, LLM tokens per day) set the ceiling. Limits an admin assigns to a workspace or tenant can never exceed that ceiling, and a request is allowed only if the tenant, workspace and organization budgets all have room. Valkey enforces per-tenant query rates and a per-workspace concurrency cap on generation. Spend alerts fire at 80 percent, and circuit breakers protect the LLM provider budget.

### 13.8 Retention versus immutability

Retention is a per-organization schedule with a legal-hold flag that blocks deletion. HIPAA documentation generally must be kept for six years (45 CFR 164.316(b)(2)(i)); counsel confirms audit-log and document retention per deployment (D10). Deletion is crypto-shredding of payloads and document content while the metadata chain stays, which is safe because metadata contains no content. The chain stays verifiable after deletion, and the tombstone ledger (section 12.9) records what was deleted and when.

### 13.9 Compliance mapping (for counsel review)

| Requirement (summary) | Design element |
| --- | --- |
| HIPAA access control, unique user identification (164.312(a)(1), (a)(2)(i)) | Auth0 identities, one membership per user, RBAC plus grants plus RLS |
| HIPAA emergency access procedure (164.312(a)(2)(ii)) | Emergency access (section 5.7) |
| HIPAA audit controls (164.312(b)) | Hash-chained, anchored audit (section 13.3) |
| HIPAA integrity (164.312(c)(1)) | Immutable chunks with content hashes; validator integrity check V3 |
| HIPAA person or entity authentication (164.312(d)) | Mandatory MFA; passkeys for privileged roles |
| HIPAA transmission security (164.312(e)(1)) | TLS or mTLS everywhere |
| HIPAA minimum necessary and role-based access (164.308(a)(4)) | Grants with tier ceilings; private documents; walls |
| HIPAA documentation retention (164.316(b)(2)(i)) | Retention schedules and legal hold (section 13.8) |
| BAAs with processors | Auth0, LLM, embedding, OCR and hosting providers (section 25) |
| Attorney-client privilege and confidentiality | Privilege tags, private documents, walls, no cross-matter retrieval, no training on customer data |
| Ethical screening | Walls with two-person lifting (section 5.6); counsel confirms rules per jurisdiction |

This table is a design aid, not legal advice.

## 14. Platform operator access

### 14.1 Principles

Operators are our own staff and sit outside every organization. They have **no standing access** to customer data or production infrastructure. Every access is requested, approved by someone else, time-boxed, recorded and visible to the affected customer. The earlier documents mention operators in three places and never say who they are or how access ends; this section defines it (DEF-25).

### 14.2 Identities and roles

Operators sign in through a separate identity provider (a dedicated Auth0 tenant `platform-<env>` or the company's own IdP), never through customer Auth0 tenants, with passkeys mandatory and a device certificate required to reach the operator ingress.

| Operator role | May do | May not |
| --- | --- | --- |
| `operator_sre` | Request JIT infrastructure access; deploy; operate pipelines and clusters | Read content; approve own access; approve key operations |
| `operator_support` | Request JIT control-plane metadata access and customer-approved content sessions through the product's support view | Open raw database or storage access to content |
| `security_officer` | Approve infrastructure JIT; verify identity for recoveries and signatories; review audit | Hold key custody; access content |
| `key_custodian` | Approve key operations in KeyGuard (at least two custodians exist; one is never the same human as `security_officer`) | Initiate organization deletion; read content |
| `operator_admin` | Manage operator accounts and roles | Access customer data or keys |

Operator accounts are named individuals, background-checked, trained as workforce members under HIPAA, reviewed quarterly, and removed the day they leave.

### 14.3 Access types and approvals

| Access type | Approver | How access is granted | What it can reach |
| --- | --- | --- | --- |
| Infrastructure shell or cluster access | A different operator `security_officer` or `operator_sre` | Just-in-time through a recorded access broker (cloud session manager or a Teleport-class tool) with a short-lived role | Infrastructure only; database access uses ephemeral credentials for `ops_metadata_ro`, a role with no policy on content tables |
| Control-plane metadata (organizations, admins, usage) | The organization's Super Admin | A scoped support principal minted by the Gateway; read-only | The same tables the Super Admin policy allows |
| Customer content (a document or query for a ticket) | The workspace admin | The product's support view, using a context token for a `support` principal limited to the named documents or queries; read-only; no export | Only what the approval names |
| Key operations | Two `key_custodian`s plus the customer-side approvers in section 12.6 | KeyGuard workflow | Key lifecycle only |
| Emergency (customer unreachable) | None for content | Infrastructure stabilization only; the platform cannot read content without approval. Legal compulsion is handled by counsel and the contract's notice terms, not by an operator shortcut | n/a |

### 14.4 Limits and lifecycle

All operator sessions follow the access-session lifecycle (section 6.8): `requested` → `approved` → `active` → `expired` or `revoked` → `reviewed`.

| Type | Default duration | Maximum | Renewal | Auto-expiry |
| --- | --- | --- | --- | --- |
| Infrastructure | 4 hours | 24 hours | New approval | Role revoked by the broker; tokens carry `exp` |
| Control-plane metadata | 4 hours | 8 hours | New approval | Support principal's `pv` bumped |
| Content | 1 hour | 4 hours | New approval | Support principal's `pv` bumped |
| Unused approved request | 24 hours to activate | n/a | n/a | Expires |

Every grant creates an audit event that appears in the customer's own audit view. A monthly report lists all operator access per organization. Operator audit is its own hash chain, anchored like the others.

### 14.5 What operators can never do

Read content without customer approval; hold a standing database superuser or migration-owner credential; sign context tokens; release a sealed workspace alone; destroy keys alone; approve their own access; or disable the audit path. These are enforced by role and key policies, tested in G9.7, and listed in the operator handbook.

### 14.6 Lost Super Admin (owner recovery)

If the Super Admin and any co-owner lose access, an authorized customer signatory requests recovery. Two operators (`security_officer` and a second `operator_support` lead) verify identity out of band, notice goes to every admin and any co-owner (who can veto), and after a 72-hour wait the identity service attaches a new Super Admin identity that then enrolls two passkeys. The old identity is blocked. The whole path is a governance request (`owner_recovery`) and is audited. Without a co-owner this path is the only recovery, which is why production organizations are strongly encouraged to name one (section 7.5).

## 15. API surface

### 15.1 Rules for every endpoint

- All IDs are opaque UUIDs. `org_id` and `workspace_id` never appear in paths, queries or bodies; they come from the principal.
- A resource outside the caller's scope returns 404 (not 403), so existence is not revealed. A system-level refusal (for example "no filter can be built") returns 403.
- State-changing POST, PUT, PATCH and DELETE accept an `Idempotency-Key`; a use is counted or an effect applied once.
- Errors use `application/problem+json` (RFC 9457) with uniform text for security-sensitive failures.
- "Step-up" means a fresh authentication within 5 minutes at the required strength (section 8.7).
- Each service publishes an OpenAPI document under `contracts/openapi/`. The route allow-list, the generated frontend client and the authorization tests all come from `contracts/authz-matrix.yaml` and these documents, so they cannot drift apart (G3.6).
- Roles: **SA** Super Admin or co-owner, **AD** Admin, **TE** Tenant, **ON** onboarding scope, **OP** operator roles.

### 15.2 Onboarding (audience `onboarding`)

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `POST /v1/onboarding/organization` | ON | no | Create an organization (starts the provisioning saga) |
| `POST /v1/onboarding/join-admin` | ON | no | Submit an Organization Code |
| `POST /v1/onboarding/join-tenant/preview` | ON | no | Validate an Admin Code and return the admin's display name; consumes no use; same error as a failed join for any invalid code |
| `POST /v1/onboarding/join-tenant` | ON | no | Submit an Admin Code |
| `GET /v1/onboarding/status` | ON, pending | no | Membership state |

### 15.3 Session

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `GET /v1/me` | any member, including a Super Admin of a `pending` organization | no | Principal, states, capabilities, `auth_strength`, `has_backup_authenticator`; capabilities are limited to enrollment and status while the organization is `pending` |
| `GET /v1/me/authenticators` | any member | no | Count and types of registered authenticators (no secrets) |

### 15.4 Organization (Super Admin and co-owner)

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `GET /v1/org`, `PATCH /v1/org/settings` | SA | PATCH | Settings: approval mode, retention schedule, deployment type, region, SSO connection, delivery policy defaults |
| `POST /v1/org/code` | SA | yes | Generate the Organization Code for the first time (shown once) |
| `POST /v1/org/code/rotate` | SA | yes | Rotate the Organization Code |
| `POST /v1/org/invites` | SA | yes | Create an email-bound invite code: kind `admin` (Organization Code bound to one email) or `successor` (bound to a frozen workspace, section 7.8) |
| `GET /v1/org/admins`, `GET /v1/org/admins/{id}` | SA | no | List and inspect admins (counts only, never tenants) |
| `POST /v1/org/admins/{id}/approve`, `/reject`, `/suspend`, `/reactivate` | SA (co-owner for owner-linked admins) | yes | Admin lifecycle |
| `DELETE /v1/org/admins/{id}` | SA | yes | Remove an admin (workspace becomes frozen) |
| `PUT /v1/org/admins/{id}/quotas` | SA | yes | Set admin and workspace quotas under the organization ceiling |
| `GET /v1/org/workspaces`, `GET /v1/org/workspaces/{id}` | SA | no | Workspace metadata and state only |
| `GET /v1/org/audit` | SA | no | Org-level and admin-level events |
| `POST /v1/org/co-owner/invite`, `DELETE /v1/org/co-owner` | SA | yes | Invite or remove a co-owner (invite becomes a `co_owner_set` request) |
| `POST /v1/org/co-owner/accept` | invitee | yes | Accept with a passkey |

### 15.5 Governance requests

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `POST /v1/governance-requests` | SA or AD per kind | yes | Create a request. Kinds: `successor_transfer`, `private_read_enable`, `wall_lift`, `workspace_unseal`, `workspace_destroy`, `org_delete`, `co_owner_set` (section 6.7) |
| `GET /v1/governance-requests`, `GET /v1/governance-requests/{id}` | SA, AD within their scope | no | List and inspect |
| `POST /v1/governance-requests/{id}/approve` | approver set for the kind | yes | Approve (must be a different human from the initiator and other approvers) |
| `POST /v1/governance-requests/{id}/reject`, `/cancel` | approver or initiator | reject: no; cancel: no | Cancel is always allowed for the initiator (restoring direction) |

### 15.6 Workspace (Admin)

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `GET /v1/workspace/policy`, `PATCH /v1/workspace/policy` | AD | PATCH | `admin_can_read_private` (via governance), emergency access, join policy, default visibility, retention override, delivery mode and `on_fail` |
| `POST /v1/workspace/code` | AD | yes | Generate the first Admin Code (shown once) |
| `POST /v1/workspace/code/rotate` | AD | yes | Rotate the Admin Code |
| `GET /v1/workspace/tenants` | AD | no | List tenants |
| `POST /v1/workspace/tenants/{id}/approve`, `/reject`, `/suspend`, `/reactivate` | AD | no | Tenant lifecycle |
| `DELETE /v1/workspace/tenants/{id}` | AD | yes | Remove a tenant (private documents move to the holding queue) |
| `PUT /v1/workspace/tenants/{id}/grants` | AD | no | Matter or patient grants with tier ceilings and optional expiry |
| `GET /v1/workspace/matters`, `POST /v1/workspace/matters`, `PATCH /v1/workspace/matters/{id}`, `DELETE /v1/workspace/matters/{id}` | AD | no | Matter and patient taxonomy |
| `GET /v1/workspace/walls`, `POST /v1/workspace/walls` | AD | no | List and create walls (instant). Lifting uses `wall_lift` |
| `GET /v1/workspace/break-glass`, `POST /v1/workspace/break-glass` | AD | yes | List sessions; start a private-document read session with a stated reason |
| `POST /v1/workspace/break-glass/{id}/end` | AD | no | End a session |
| `GET /v1/workspace/held-documents` | AD | no | Metadata-only holding queue (ID, size, date, matter label) |
| `POST /v1/workspace/held-documents/{id}/reassign`, `DELETE /v1/workspace/held-documents/{id}` | AD | yes | Reassign to a tenant on the same matter, or delete (key destroyed) |
| `GET /v1/workspace/review-queue`, `POST /v1/workspace/review-queue/{id}/close` | AD | close: no | OCR review items and emergency-access post-hoc reviews |
| `GET /v1/workspace/operator-access-requests` | AD | no | Operator requests awaiting approval |
| `POST /v1/workspace/operator-access-requests/{id}/approve`, `/deny`, `/revoke` | AD | approve: yes | Approve, deny, or revoke operator access to content |
| `GET /v1/workspace/audit` | AD | no | Workspace audit events |

### 15.7 Data plane (Admin and Tenant)

| Endpoint | Roles | Step-up | Purpose |
| --- | --- | --- | --- |
| `POST /v1/query` (SSE) | AD, TE | no | Ask a question. Optional `matter_ids` narrows the scope within what the caller may already read; it can never widen it |
| `GET /v1/documents`, `GET /v1/documents/{id}` | AD, TE | no | List and view metadata |
| `POST /v1/documents/uploads`, `POST /v1/documents/{id}/complete` | AD, TE | no | Two-step upload (section 11.1) |
| `PATCH /v1/documents/{id}` | AD, TE (owner) | no | Change visibility, matter or tier; writes the re-index outbox row |
| `DELETE /v1/documents/{id}` | AD, TE (owner) | no | Delete and crypto-erase |
| `GET /v1/documents/{id}/download` | AD, TE | no | Decrypting download (section 12.3) |
| `POST /v1/documents/{id}/ocr-review` | AD, TE (owner) | no | Approve or correct quarantined pages |
| `GET /v1/citations/{request_id}/{alias}` | AD, TE | no | Source chunk, page and highlighted span; visibility re-checked |
| `POST /v1/exports` | AD, TE | yes | Export answers with citations or audit history |
| `POST /v1/access/emergency`, `POST /v1/access/emergency/{id}/end`, `GET /v1/access/emergency` | TE (medical workspaces) | no | Clinical emergency access (section 5.7) |
| `GET /v1/audit/me` | AD, TE | no | Own history |
| `GET /v1/health` | anonymous | no | Liveness only, no detail |

### 15.8 Operator plane (`ops.<product-domain>`, separate ingress and identity provider)

| Endpoint | Roles | Purpose |
| --- | --- | --- |
| `POST /ops/v1/access-requests` | `operator_sre`, `operator_support` | Request JIT access (infrastructure, control-plane metadata or content) |
| `GET /ops/v1/access-requests`, `POST /ops/v1/access-requests/{id}/approve`, `/deny`, `/revoke` | approver roles per type (section 14.3) | Approve, deny, revoke |
| `GET /ops/v1/orgs`, `GET /ops/v1/orgs/{id}` | `operator_support` (JIT) | Organization metadata and health |
| `POST /ops/v1/orgs/{id}/freeze` | `security_officer` | Security hold (instant, restoring-direction asymmetry) |
| `POST /ops/v1/orgs/{id}/release` | `security_officer` plus a second operator | Release a hold |
| `POST /ops/v1/recoveries`, `POST /ops/v1/recoveries/{id}/approve` | `security_officer`, `operator_support` lead | Super Admin recovery (`owner_recovery`) |
| `POST /ops/v1/keyguard/requests`, `POST /ops/v1/keyguard/requests/{id}/approve` | `key_custodian` | Key lifecycle operations (section 12.6) |
| `GET /ops/v1/audit` | `security_officer` | Operator audit chain |

### 15.9 Internal endpoints (not routable from outside)

| Service | Endpoints (prefix `/internal/v1/`) |
| --- | --- |
| `identity` | `principal/{sub}` (principal resolution input), `revocations` (publish), `provisioning/*` |
| `retrieval` | `search`, `scope/{request_id}` (diagnostics, operator-approved only) |
| `generation` | `answer` (SSE, takes `request_id` and the question) |
| `citation_validator` | `validate-stream` (token deltas in, signed sentence verdicts out), `validate-answer` (buffered mode) |
| `ingestion` | `documents/*` lifecycle, `documents/{id}/versions`, `index/reconcile` |
| `audit` | `events`, `payloads/{id}` (decrypting read), `verify`, `anchors` |

## 16. Data model

### 16.1 Conventions

UUIDv7 primary keys; `timestamptz` everywhere; every tenant-bearing table carries `org_id` and, where applicable, `workspace_id`; foreign keys are composite so a row cannot point across workspaces; `FORCE ROW LEVEL SECURITY` on every table; status columns are enums with transition tables (section 6.1); soft secrets (codes, keys) are stored hashed or wrapped, never plaintext.

### 16.2 Core tables

| Table | Key columns | Notes |
| --- | --- | --- |
| `orgs` | `id`, `auth0_org_id`, name, deployment type, region, state, retention policy, legal hold flag | One per Super Admin |
| `users` | `id`, `auth0_sub`, email (encrypted), email blind index, `auth_strength_last` | One per Auth0 identity |
| `memberships` | `user_id`, `org_id`, `workspace_id`, role, state, state reason, `principal_version`, `scope_version`, `scope_hash`, `approved_by`, `owner_linked` | Unique on `user_id` in v1; `approved_by` cannot equal `user_id` (CHECK; the Super Admin's first membership is created by the saga with a system approver). Triggers on grants, walls, exceptions, sessions and workspace flags maintain `scope_version` and `scope_hash` |
| `principal_v` (view) | user ID, org, workspace, role, states, `principal_version`, `scope_version`, `scope_hash` | The only relation the Gateway can read; no grants, walls or content |
| `workspaces` | `id`, `org_id`, `admin_user_id`, state, policy flags (`admin_can_read_private`, `emergency_access`, join policy, delivery mode, `on_fail`) | One per admin |
| `join_codes` | `id`, kind (`org`, `admin`, `successor`), `org_id`, `workspace_id`, lookup ID, hash, `pepper_id`, expiry, max uses, used count, bound email (invites), state | Hash only |
| `join_attempts` | lookup ID, user, IP, outcome, true reason | Feeds rate limits and alerts |
| `governance_requests`, `governance_approvals` | kind, target, initiator, state, wait-until, expires, approver, approved-at, authentication proof reference | Section 6.7 |
| `matters` | `id`, `org_id`, `workspace_id`, label, type (matter or patient) | |
| `matter_grants` | `workspace_id`, `matter_id`, `user_id`, `max_tier`, `granted_by`, `expires_at` | Drives `scope_hash` |
| `matter_walls` | `workspace_id`, `matter_id`, `user_id`, `reason_code`, `created_by`, `effective_from` | Explicit deny (section 5.6) |
| `access_exceptions` | `workspace_id`, `user_id`, `matter_id`, kind (`emergency`), `expires_at`, `review_state` | Section 5.7 |
| `break_glass_sessions` | `workspace_id`, `admin_user_id`, reason, `expires_at` | Section 5.8 |
| `documents` | `id`, `org_id`, `workspace_id`, `owner_user_id`, `matter_id`, visibility, tier, status, `current_version`, `retention_until`, `legal_hold` | CHECK: visibility `matter` requires `matter_id`; legal hold blocks deletion (DEF-48) |
| `document_versions` | `doc_id`, version, `text_source`, `index_state`, object key, `embedding_version` | |
| `doc_keys`, `workspace_keys`, `org_keys`, `audit_keys` | wrapped key, key version, state, `deletion_protection` (org keys) | Section 12 |
| `chunks` | Section 11.2 fields | Immutable per version |
| `retrieval_records` | `request_id`, `user_id`, `scope_hash`, items (chunk ID, version, hash, alias, rank, scores, dropped reason) | Insert-only for `retrieval`; select-only for `generation` and `citation_validator` |
| `index_outbox` | doc, version, operation, attempts, state | Written in the same transaction as the change |
| `idempotency_keys` | key, principal, request hash, response reference | |
| `audit_event`, `audit_payload`, `audit_anchor` | Section 13 | Insert only through `audit_append` |
| `deletion_tombstones` | scope, ID, time, approver references | Mirrored to the tombstone ledger outside backups |
| `quotas` | scope, limits, usage | Organization, workspace and tenant levels |
| `workspace_usage` | `workspace_id`, counts of tenants, documents and queries, token usage | Numbers only; the only workspace data the `super_admin` role may read |
| `operator_accounts`, `operator_access_grants` | role, state, expiry, approver | Separate schema with its own roles |

### 16.3 Policy summary by role

| Role | Control-plane tables | Content tables | Audit |
| --- | --- | --- | --- |
| `svc_gateway` | `principal_v` view only | none | `audit_append` execute |
| `svc_identity` and the `super_admin` policy set | full for identity; restricted subset for Super Admin | none | `audit_append`; org-scope events |
| `svc_ingestion`, `svc_retrieval`, `svc_generation`, `svc_validator` | read context only | per section 5.4 under RLS; `retrieval_records` per section 16.2 | `audit_append` execute |
| `svc_audit_reader` | none | none | read events; decrypt payloads |
| `reconciler` | none | column-level SELECT on IDs and index metadata | none |
| `ops_metadata_ro` | metadata views | none | operator chain read |

## 17. Frontend design (Next.js 16)

### 17.1 Structure and routing

```
frontend/src/
├── proxy.ts                   Auth0 route mounting, session gate, CSP nonce; replaces middleware.ts in Next.js 16
├── lib/                       auth0.ts, api-client (generated), sse.ts, capabilities.ts
├── app/
│   ├── (onboarding)/          role cards, code entry, pending status
│   ├── (app)/chat/            streamed Q&A workspace with citation side panel
│   ├── (app)/library/         upload, status, OCR review, metadata
│   ├── (app)/audit/           content scoped by role
│   ├── (super-admin)/manage-admins/     Super Admin only
│   ├── (super-admin)/governance/        requests and approvals
│   ├── (workspace-admin)/manage-tenants/   Admin only
│   ├── (workspace-admin)/walls/         ethical walls and lift requests
│   ├── (workspace-admin)/review/        OCR and emergency-access reviews
│   ├── (account)/             profile, authenticators, active sessions
│   └── api/                   BFF route handlers; the only code that holds tokens
└── components/                chat, library, audit, governance, ui
```

| Route | Super Admin | Admin | Tenant | Pending or suspended |
| --- | --- | --- | --- | --- |
| `/onboarding` | Redirect if member | Redirect if member | Redirect if member | Status page |
| `/chat`, `/library` | Redirect to Manage Admins | Yes | Yes | Blocked |
| `/audit` | Org and admin events | Workspace | Own | Blocked |
| `/manage-admins`, `/governance` (org kinds) | Yes | 404 | 404 | Blocked |
| `/manage-tenants`, `/walls`, `/review` | 404 | Yes | 404 | Blocked |

Admins start `wall_lift` and `private_read_enable` requests from `/walls` and the policy tab of `/manage-tenants`, and see their own requests there; organization-level kinds live under `/governance` for Super Admins only.

`proxy.ts` calls the BFF `/me` handler, which returns the resolved principal and a capability list; the frontend never trusts roles it decoded itself. Forbidden routes return 404 so their existence is not revealed. Hidden menu items are convenience, not control.

### 17.2 Key surfaces

- **Chat:** sentences arrive only after validation, each with its citation markers. A side panel shows the chunk, page range and highlighted span for a clicked marker; stripped sentences show the visible "could not be verified" marker. Status events (retrieving, generating, validating) keep the interface responsive while the first sentence validates.
- **Library:** upload progress, status per document including `ocr_review` with a side-by-side page image and text editor, visibility and matter controls, confidentiality tier.
- **Manage Admins (Super Admin):** admins table (state, last active, tenant count, document count, 30-day token usage) with pending requests pinned; row actions with step-up and a reason; Organization Code panel (lookup ID, dates, uses remaining; rotate; email-bound invite; secrets shown once in a copy-and-clear modal); an admin drawer with profile, status history and admin-level audit that shows counts only, never tenants; organization settings tab; co-owner management; governance center for approvals.
- **Manage Tenants (Admin):** tenants table with pending pinned; approve with a grants selector; grants editor with a preview of what the tenant could retrieve; Admin Code panel with join-policy selector; workspace policy tab; holding queue for removed tenants' private documents (metadata only); walls with a lift workflow; break-glass sessions; operator access approvals; review queue.
- **Account:** authenticator list (count and type), backup authenticator prompt, active sessions with sign-out.

### 17.3 Security and streaming rules

- **Strict CSP with nonces** (`script-src` with a per-request nonce and `strict-dynamic`, no inline scripts, no `unsafe-eval`), set from `proxy.ts`; `frame-ancestors 'none'`; `Referrer-Policy: no-referrer` on onboarding; Trusted Types where supported. Document content renders through a sanitized viewer (no raw HTML injection).
- **No tokens in the browser.** The browser holds only an opaque httpOnly, SameSite session ID; tokens live in the server-side session store. Tests assert no token appears in storage, in any cookie value or in any response body (G8.5).
- **Nonce-based CSP forces dynamic rendering.** Next.js can apply a per-request nonce only to dynamically rendered pages, so static generation and CDN caching of HTML are unavailable. This is accepted; static assets stay cacheable.
- **SSE client uses `eventsource-parser`.** The sketch in the deep-dive split each network chunk on newlines and parsed JSON, which breaks when a frame is split across chunks (DEF-36); a buffered parser is mandatory, and G8.4 tests it by slicing a real stream at every byte boundary.
- **Vercel AI SDK is not used.** The protocol has custom events (sentence, citations, warning) and the SDK adds little (D15).
- **Secrets are rendered once**, copied through a button and cleared from state on close. Destructive actions show the effect on sessions and data before confirming.
- **Generated client** from the OpenAPI contracts (`openapi-typescript` and `openapi-fetch`); no hand-written fetch to the Gateway outside `lib/api-client`.
- **Hosting:** containerized standalone build behind the same ingress as the API, so hospital and law-firm deployments can stay inside a VPC. Vercel is not required.
- **Accessibility:** WCAG 2.2 AA target, verified by axe and keyboard-only e2e flows.

## 18. Repository structure and tooling

The monorepo keeps the earlier blueprint's shape (one deployable per service, shared libraries, contracts first) and adopts current Python and Next.js conventions: a `uv` workspace with one lockfile, `src/` layout per package, small libraries instead of one `common` package so import boundaries can be enforced, and `contracts/` as a first-class directory.

```
legal-medical-qa/
├── pyproject.toml              uv workspace root; shared ruff, pytest, pyright config
├── uv.lock                     single lockfile for all Python packages
├── .python-version             3.14
├── .gitignore  .gitattributes  .editorconfig  .gitleaks.toml  .pre-commit-config.yaml
├── README.md  CONTRIBUTING.md  SECURITY.md  CODEOWNERS
├── stages.toml                 path-to-stage ownership map and gate definitions
├── STAGE                       current stage number (changed only by the gatekeeper)
├── Makefile                    up, doctor, gate, isolation, load-corpus, eval
├── compose.yaml  compose.override.yaml  compose.test.yaml
├── .env.example                every variable, documented, no secrets
│
├── docs/
│   ├── architecture.md  versions.md  compliance/  diagrams/
│   ├── adr/                    0001 service split … 0012 toolchain (list in section 24)
│   └── runbooks/               leaked-code, suspended-admin, org-recovery, key-deletion-alert,
│                               ingestion-stuck, citation-validation-failing, restore-and-shred
├── contracts/
│   ├── openapi/                gateway, identity, ingestion, retrieval, generation,
│   │                           citation-validator, audit, ops
│   ├── authz-matrix.yaml       role × route × step-up (source of the allow-list and tests)
│   ├── features.toml           feature flags bound to gates (disabled endpoints return 404)
│   ├── state-machines.yaml     every lifecycle in section 6
│   ├── claims/                 Auth0 token claim schemas and the Action's observed method names
│   └── events/                 audit, outbox and ledger JSON Schemas
├── db/
│   ├── alembic.ini  migrations/    schema, roles, transition tables, triggers
│   ├── policies/                   reviewed SQL for every RLS policy and helper function
│   └── roles/                      role and grant definitions
├── libs/                           each a package: libs/<name>/src/<name>/ and tests/
│   ├── lmqa_models/                Pydantic models, state-machine guards generated from YAML
│   ├── lmqa_auth/                  Auth0 verification, context tokens, certificates
│   ├── lmqa_db/                    scoped session, OrgRouter, boot self-test
│   ├── lmqa_keys/                  key providers (AWS KMS, OpenBao), envelope encryption, KeyGuard client
│   ├── lmqa_security/              code generation and keyed hashing, sealing (HPKE), redaction
│   ├── lmqa_vectorstore/           only holder of a Qdrant client; filter builder
│   ├── lmqa_objectstore/           S3 adapter with application-level encryption
│   ├── lmqa_audit/                 audit_append client, sealing, verification helpers
│   ├── lmqa_logging/  lmqa_telemetry/
│   └── lmqa_testing/               real-data fixtures: corpus loader, Auth0 sessions, leak scanner
├── services/                       each: src/<service>/, tests/, Dockerfile, pyproject.toml
│   ├── gateway/  identity/  ingestion/  retrieval/  generation/
│   ├── citation_validator/  audit/  ops/
│   └── (ingestion also ships worker, indexer and reconciler entry points)
├── frontend/                       Next.js 16, pnpm, TypeScript (section 17)
├── prompts/                        templates/, few_shot_examples/, registry.toml
├── eval/                           sets/ (real labeled queries), floors.toml, harness/
├── corpus/                         manifest.toml (URL, license, sha256), fetchers; data/ is git-ignored
├── infra/
│   ├── compose/                    seaweedfs, qdrant, pgbouncer, valkey, openbao, clamav, otel, grafana
│   ├── auth0/                      OpenTofu for tenants dev, ci, staging, prod and platform tenants
│   ├── keyguard/                   key policies, SCPs, KeyGuard workflow, responder, lint rules
│   ├── aws/                        accounts, KMS, buckets (anchor, tombstone, escrow), OIDC for CI
│   └── k8s/                        base, overlays (local, staging, production)
├── tools/                          gatekeeper, doctor, load_corpus, leakscan, state_machine_gen,
│                                   auth_harness (minimal real relying party for Auth0 tests before Stage 8),
│                                   mvp_report (generates and verifies run reports from system data)
├── tests/                          e2e/, isolation/, contract/, load/, chaos/, controls.md
└── .github/workflows/              ci, gates, isolation, nightly-live, security, release
```

| Earlier path | Now | Reason |
| --- | --- | --- |
| `libs/common/{auth,security,models,logging,telemetry}` | separate `lmqa_*` packages | Import-linter can enforce who may use what |
| `docs/api-contracts/*.yaml` | `contracts/openapi/` | Contracts feed tooling and tests, not just readers |
| `db/seed/` | `corpus/` plus `tools/load_corpus` | Data enters through the real onboarding API, not SQL inserts |
| `scripts/seed_demo_tenant.py`, `scripts/run_citation_eval.py` | `tools/load_corpus`, `eval/harness` | Real data; evaluation lives with its floors |
| `frontend/middleware.ts` | `frontend/src/proxy.ts` | Next.js 16 convention |
| `infra/local/{minio,qdrant,nginx}` | `infra/compose/…` with SeaweedFS | MinIO community edition is in maintenance mode |
| `infra/local/oidc-mock` (v2.1) | removed | Real Auth0 `dev` and `ci` tenants |
| Single `docker-compose.yml` | `compose.yaml` plus override and test files | Current Compose naming; no `version:` key |

`CODEOWNERS` assigns security review to `db/policies/`, `contracts/authz-matrix.yaml`, `contracts/state-machines.yaml`, `libs/lmqa_keys/`, `libs/lmqa_auth/`, `infra/keyguard/` and `infra/auth0/`. `stages.toml` and the gatekeeper tool (section 19.6) control what code may be merged at which stage.

## 19. Quality system: real data, `pytest`, `ruff` and gates

### 19.1 Real-data rules

"Don't use fake data from the start" is turned into ten rules that the toolchain enforces where it can.

| Rule | Statement | Enforcement |
| --- | --- | --- |
| R1 | **Real documents only.** No generated text, lorem ipsum or invented contracts or charts. Every fixture comes from the corpus manifest | `corpus/manifest.toml` is the only fixture source; tests load through `lmqa_testing` |
| R2 | **Real systems only.** No mocks, fakes, stubs or in-memory substitutes for PostgreSQL, Qdrant, Valkey, the object store, KMS, Auth0, the LLM, the embedding, re-ranking and entailment models, or SMTP and IMAP | `ruff` TID251 bans `unittest.mock`, `pytest_mock`, `respx`, `responses`, `faker`, `factory` and `freezegun` (G0.11) |
| R3 | **Documented provenance.** Each corpus item records URL, licence, retrieval date and SHA-256. Items with non-commercial or restrictive licences are flagged internal-evaluation-only or excluded | Gate G0.8 and legal review of the manifest |
| R4 | **No customer data outside production.** No real PHI, client files or privileged material in dev, CI or staging. Credentialed datasets such as MIMIC-IV-Note require a data use agreement whose terms restrict sending data to third-party LLM APIs; they are an opt-in lane with self-hosted models only, never in shared CI | Network egress rules on test environments; manifest review |
| R5 | **Real accounts, real flows.** Users are real Auth0 identities with project-owned mailboxes. Data enters through the product's own onboarding and upload APIs, never through SQL inserts | `lmqa_testing` offers no SQL seeding helper; the database roles used by tests are the service roles |
| R6 | **Labeled negative controls are allowed.** The EICAR antivirus test file, planted secrets for gitleaks, crafted malformed JWTs, adversarial prompts and XSS strings from public datasets, and injected faults are instruments, not data. Each is listed in `tests/controls.md` and marked `control` | `@pytest.mark.control` required; unlisted controls fail review |
| R7 | **Time acceleration only through configuration.** Waiting periods (72 hours, 30 days, 24 hours) are configuration values; tests use short values; a lint test fails if the production profile is below policy minimums | G2.10, G11.1 |
| R8 | **Scale by replication.** Load tests replicate real documents into many workspaces (new IDs, per-document keys) and never synthesize text | `tests/load` fixtures |
| R9 | **Recorded model responses only in the fast lane.** Recorded LLM responses may serve the fast pull-request lane if recorded from live calls less than 14 days old. The nightly lane and every stage gate run live; a gate result without a live run is invalid | Gatekeeper checks the `live` marker count |
| R10 | **Ground truth is published or human.** Evaluation labels come from published datasets or reviewers qualified in the domain, never from the model under test | `eval/` provenance file |

Appendix B describes the corpus and its candidate sources. One honest gap: license-clean public sets of real clinical notes with SOAP structure are scarce. Public medical coverage comes from open-access case reports (JATS XML), drug labels (SPL XML) and agency guidelines; real SOAP-style notes arrive only through the credentialed lane or a pilot under a BAA (Stage 11).

### 19.2 Test taxonomy

| Marker | Meaning | Real dependencies | Lane |
| --- | --- | --- | --- |
| `unit` | Pure functions only: no I/O, no clock, no network | none | Every push |
| `integration` | One or more services against real infrastructure | PostgreSQL, PgBouncer, Valkey, Qdrant, object store, ClamAV, embedding models | Every push |
| `contract` | OpenAPI, claims, state machines and authorization matrix validated against implementation | running services | Every push |
| `live_auth0` | Real Auth0 `ci` tenant (Playwright with virtual authenticator) | Auth0, IMAP mailbox | Every pull request (subset); nightly (full) |
| `live_kms` | Real KMS and OpenBao | AWS dev or CI account, OpenBao | Every pull request (subset); nightly (full) |
| `live_llm` | Real model calls with a spend cap | LLM provider | Nightly and every stage gate |
| `e2e` | Browser flows through the whole stack | everything | Every pull request (smoke); nightly (full) |
| `isolation` | The cross-scope suite (section 21) | everything | Required check on every merge |
| `perf`, `chaos` | Load budgets and fault injection (section 22) | everything at scale | Nightly and stage gate for Stage 10 |
| `control` | Planted-fault negative controls | as needed | Same lane as the test they accompany |
| `stage0` … `stage11` | The stage whose gate the test belongs to | | Gate runs |

Every test carries exactly one stage marker and one of `unit`, `integration`, `contract`, `e2e`. Tests are randomized in order (`pytest-randomly`) and run in parallel with `pytest-xdist` where fixtures allow.

### 19.3 `ruff` configuration

`ruff` 0.16 turns on 413 rules by default and formats Markdown code blocks. To stop upgrades from silently changing the gate, the rule set is **explicit**; the config hash is recorded in every gate attestation.

```toml
# pyproject.toml (workspace root) — gate definition, not application code
[tool.ruff]
target-version = "py314"
line-length = 100
extend-exclude = ["db/migrations/versions", "corpus/data"]

[tool.ruff.lint]
select = ["ALL"]
ignore = [
  "COM812", "ISC001",      # conflict with the formatter
  "D203", "D213",          # conflicting docstring styles
  "CPY", "FIX", "TD",      # policies handled in review
]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"unittest.mock".msg = "R2: use real systems"
"pytest_mock".msg = "R2: use real systems"
"respx".msg = "R2: use real systems"
"responses".msg = "R2: use real systems"
"faker".msg = "R1: no fake data"
"factory".msg = "R1: no fake data"
"freezegun".msg = "R7: time acceleration through configuration only"
"pydantic.v1".msg = "Pydantic v2 only"
"sqlalchemy.create_engine".msg = "use lmqa_db scoped session"
"psycopg.connect".msg = "use lmqa_db scoped session"

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101", "PLR2004", "ANN", "D", "S105", "S106"]
"db/migrations/**" = ["E501", "D"]
"libs/lmqa_db/**" = ["TID251"]
```

`select = ["ALL"]` includes security rules (`S`, bandit-derived), async rules (`ASYNC`), FastAPI rules (`FAST`), timezone-aware datetimes (`DTZ`), print bans (`T20`), SQL-injection patterns (`S608`), and exception and logging hygiene. CI runs `ruff format --check` and `ruff check` with no `--fix`, and fails on any finding and on any unused suppression comment. Frontend code is checked by ESLint (flat config) with `typescript-eslint` strict-type-checked and the Next.js plugin, plus `tsc --noEmit`.

### 19.4 `pytest` configuration

```toml
[tool.pytest.ini_options]
minversion = "9.1"
addopts = "-ra --strict-markers --strict-config --import-mode=importlib"
xfail_strict = true
asyncio_mode = "strict"
timeout = 180
filterwarnings = ["error"]
markers = [
  "unit", "integration", "contract", "e2e", "isolation", "perf", "chaos",
  "live_auth0", "live_kms", "live_llm", "control",
  "stage0", "stage1", "stage2", "stage3", "stage4", "stage5", "stage6",
  "stage7", "stage8", "stage9", "stage10", "stage11",
]
```

`--strict-markers` and `--strict-config` catch typos; `filterwarnings = ["error"]` turns warnings into failures; `xfail_strict` makes an unexpectedly passing expected-failure fail. Flaky tests are fixed, not retried: no rerun plugin is installed.

### 19.5 Coverage and mutation thresholds

| Scope | Line coverage | Branch coverage | Mutation score |
| --- | --- | --- | --- |
| All Python packages | 90% | 85% | n/a |
| Security-critical: `lmqa_auth`, `lmqa_keys`, `lmqa_security`, `lmqa_db`, `services/identity`, `services/gateway` auth modules | 95% | 90% | 75% on `lmqa_security` and `lmqa_keys` |
| `services/citation_validator` | 95% | 90% | 80% |
| Frontend | Unit tests for all pure helpers; e2e covers every route in the route matrix | n/a | n/a |

Coverage is a floor, not a goal; the differential, provenance and state-machine suites carry the correctness argument.

### 19.6 Gate mechanics

`make gate STAGE=n` runs, in order: `uv sync --frozen`; `ruff format --check`; `ruff check`; `pyright`; frontend lint and type check; `import-linter`; contract linting; `gitleaks`; dependency audit (`pip-audit` and `pnpm audit`); `pytest -m "stage0 or … or stage{n}"` with coverage; the stage's special suites (section 20); and finally writes `gates/stage-{n}.json`: commit SHA, tool versions, `ruff` config hash, test counts by marker, coverage, live-lane counts, durations, and pass or fail. In CI the file is signed with cosign keyless signing and published as an attestation for that commit.

```toml
# stages.toml (excerpt) — ownership of paths by stage
[stage.0]
owns = ["pyproject.toml", "tools/**", "infra/compose/**", "infra/auth0/**", "corpus/**", "contracts/**", ".github/**"]
[stage.1]
owns = ["db/**", "libs/lmqa_db/**", "libs/lmqa_keys/**", "libs/lmqa_security/**", "libs/lmqa_audit/**", "infra/keyguard/**", "infra/aws/**"]
[stage.2]
owns = ["services/identity/**", "libs/lmqa_models/**"]
[stage.3]
owns = ["services/gateway/**", "libs/lmqa_auth/**"]
```

The **gatekeeper** (`tools/gatekeeper`) enforces three rules as a required status check:

1. A pull request may modify only paths owned by stages up to `STAGE + 1`. Code for stage `n + 2` is rejected.
2. `STAGE` advances to `n + 1` only through a gatekeeper commit that requires a valid signed attestation for stage `n` on the exact commit, with no skips outside a listed set of platform markers and a non-zero live-lane count where the stage requires one.
3. **Gates are cumulative.** Every pull request re-runs all gates from stage 0 to the current stage. Changing code owned by an earlier stage re-opens that stage's gate for that suite.

**Profiles and feature flags.** `stages.toml` also defines gate **profiles**. `full` is the default and the only profile valid for production. `mvp` (release M1, described in the MVP Prototype Report and Process) lists which gates are required, which run at reduced size and which are bound to disabled features. A profile may reduce sizes and feature scope but never a safety threshold. Deferred features are listed in `contracts/features.toml`; a flag may be enabled only with signed attestations from its bound gates, and the gatekeeper checks this.

### 19.7 Definition of done and failure protocol

A stage is **done** only when every gate check in its table passes on a clean CI run, twice in a row, with zero skipped checks and zero waivers. Items that do not gate the stage are listed explicitly as "deferred" in the stage's table and nowhere else.

On any failure the line stops: write a failing test that reproduces the defect, fix the cause, add the regression test, re-run the cumulative gate. A failure in an isolation, authentication, key or audit check also triggers a short incident review recorded as an ADR addendum, because those failures mean the design claim was wrong, not only the code.

## 20. Staged delivery plan

```mermaid
flowchart LR
  S0["0 Foundation"] --> S1["1 Data layer and keys"]
  S1 --> S2["2 Identity and onboarding"]
  S2 --> S3["3 Gateway and trust"]
  S3 --> S4["4 Ingestion"]
  S4 --> S5["5 Retrieval"]
  S5 --> S6["6 Generation"]
  S6 --> S7["7 Validation and gated delivery"]
  S7 --> S8["8 Frontend"]
  S8 --> S9["9 Governance, audit, operators"]
  S9 --> S10["10 System verification"]
  S10 --> S11["11 Production readiness"]
```

Each stage lists its goal, what it builds, and a **gate table**. A gate row is a check with a pass criterion; all rows must pass. Numeric floors for retrieval and validation quality are recorded in `eval/floors.toml` from the Stage 4 and 5 baselines and may never be lowered without an ADR. Targets for performance are in section 22.

### Stage 0 — Foundation and real dependencies

**Goal.** A reproducible toolchain and every real dependency proven reachable before any product code exists.
**Builds.** Repository skeleton (section 18), `uv` workspace and lockfile, CI, `stages.toml` and the gatekeeper, `import-linter` contracts, Compose infrastructure (PostgreSQL 18, PgBouncer, Valkey, Qdrant, SeaweedFS, OpenBao, ClamAV, observability), OpenTofu for the Auth0 `dev` and `ci` tenants and AWS dev and CI accounts (KMS, anchor bucket with Object Lock, OIDC for CI), `make doctor`, `tools/auth_harness` (a minimal, real Auth0 relying party so backend stages can log in before the frontend exists), corpus manifest and fetchers, OpenAPI skeletons, the queue spike, ADRs 0001 to 0012, `docs/versions.md`.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G0.1 | Reproducible environment | `uv sync --frozen` succeeds on a clean checkout under Python 3.14; resolved versions equal `docs/versions.md`; tool versions asserted by a test |
| G0.2 | `ruff` | `ruff format --check` and `ruff check` report zero findings under the pinned version and recorded config hash |
| G0.3 | Types | `pyright` clean (strict on `libs/`) |
| G0.4 | Infrastructure smoke | Every container healthy; PostgreSQL 18.x, Qdrant 1.19.x and Valkey 9.x reported by the servers match the ledger; SeaweedFS passes the capability probe (versioning, presigned URLs, multipart, checksum headers) or the alternate is selected |
| G0.5 | Import boundaries | `import-linter` passes; a deliberately violating fixture package makes it fail (negative control) |
| G0.6 | Secrets hygiene | gitleaks clean; a planted secret is detected (control); `.env` is ignored and `.env.example` is not |
| G0.7 | Auth0 as code | `tofu plan` shows no drift for `dev` and `ci`; a real sign-up and login complete through Playwright with a virtual authenticator against `tools/auth_harness` (a minimal real Authorization Code plus PKCE client registered in the tenant, used by every backend stage until the Stage 8 frontend exists); claim-shape snapshot recorded |
| G0.8 | Corpus | Every manifest item downloads with the recorded SHA-256; licences recorded and reviewed; counts meet minimums (for example 150 legal and 150 medical documents, covering born-digital PDF, scanned PDF, JATS XML, SPL XML and DOCX) |
| G0.9 | Real dependency doctor | KMS create, encrypt, decrypt, disable and enable round trip; Object Lock write succeeds and delete is refused; one real LLM call within budget; IMAP read works; embedding and re-ranker models load and process a real chunk; ClamAV signatures are current |
| G0.10 | Contracts | OpenAPI lint has zero errors; generated TypeScript client compiles; `authz-matrix.yaml` and `state-machines.yaml` validate against their schemas |
| G0.11 | No-mocks rule | A file importing `unittest.mock` fails `ruff` (control); `faker` is absent from the lockfile |
| G0.12 | Documentation | Every Mermaid diagram renders in CI; link check passes; ADRs 0001 to 0012 exist |
| G0.13 | Queue and connection routing spike | Through the real PgBouncer and PostgreSQL: enqueue inside the application's own transaction via the SQL defer function (job invisible until commit, absent on rollback); per-workspace slot locks bound concurrency; workers on direct connections receive `NOTIFY`; throughput meets the Stage 4 target. If any fails, Celery is adopted and ADR 0011 records why |

### Stage 1 — Data layer and key management

**Goal.** The database and the key system enforce isolation and deletion on their own, before any service exists.
**Builds.** Alembic baseline; roles and grants; FORCE RLS policies for section 5.4; helper functions and indexes; boot self-test library; scoped session helper and `OrgRouter`; state-machine transition tables and triggers generated from `state-machines.yaml`; audit tables, `audit_append`, hash chain and checkpoints; key providers (AWS KMS, OpenBao), envelope encryption, DEK cache; KeyGuard policies, service control policies, responder and lint rules; outbox and tombstone ledger; `lmqa_testing`.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G1.1 | Migrations | Apply and roll back on an empty and a populated database; schema snapshot matches |
| G1.2 | Role and table audit | Every service role is non-owner and `NOBYPASSRLS`; every table has FORCE RLS; no `PUBLIC` grants (catalog queries) |
| G1.3 | Fail closed | With no context every table returns zero rows, including on a pooled connection that already ran a transaction with a context (empty-string setting, no cast error); the boot self-test refuses to start when a test database has FORCE RLS removed |
| G1.4 | Policy equals oracle | At least 20,000 generated scenarios (roles, walls, tiers, grants, exceptions, sessions, frozen workspaces, private and matter documents); RLS results equal the Python oracle for every role, table and operation |
| G1.5 | Super Admin boundary | As `super_admin`, documents, chunks, tenant memberships, walls and audit payloads return zero rows; `workspace_usage` is readable |
| G1.6 | Composite foreign keys | Inserting a cross-workspace reference fails for every foreign key |
| G1.7 | Pooler safety | On the real PgBouncer with prepared statements configured for pooling, 10,000 interleaved transactions from different principals never observe each other's context; the SQL scan finds no session-state statements on the request path |
| G1.8 | Audit | `audit_append` builds a valid chain; UPDATE and DELETE are rejected; a tamper made on an isolated copy is detected; a chain verifies across a partition detach checkpoint |
| G1.9 | State machines | Generated tests pass for membership, workspace, organization, document, join code, governance request and access session, including every illegal pair |
| G1.10 | Envelope encryption | Round trip; changed associated data fails; wrong-workspace unwrap fails; DEK cache keeps KMS calls within the computed bound under concurrency |
| G1.11 | Shredding | OpenBao: deleting a document key makes it undecryptable; deleting the CMK makes everything undecryptable; restoring a backup and replaying the tombstone ledger keeps deleted data unreadable. AWS KMS: schedule deletion, observe `PendingDeletion` and failing decrypt, cancel, observe `Disabled`, re-enable, decrypt works |
| G1.12 | KeyGuard preventive controls | Policy simulation denies schedule, disable and key-policy changes for every principal except the two named roles; real attempts by service and admin roles are refused; lint fails any production key with a window under 30 days; the responder cancels an unapproved scheduled deletion within 60 seconds |

### Stage 2 — Identity and onboarding on Auth0

**Goal.** Create organizations, admins and tenants through real Auth0, with approvals, passkeys and two-person governance.
**Builds.** Identity service, join codes, onboarding paths A, B and C, provisioning saga, approvals, governance requests, Auth0 sync and revocation fan-out, co-owner flow, notifications over real SMTP, Auth0 Actions.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G2.1 | Organization creation | Playwright against the real `ci` tenant: saga completes; Auth0 Organization, roles, KMS key and replica, rows and policies exist; replay with the same idempotency key creates nothing new |
| G2.2 | Saga failure injection | Killing the process at each step leaves the organization `pending` and invisible; retry completes; compensation leaves no orphan Auth0 or KMS resources (inventory diff is empty) |
| G2.3 | Join admin | A pending user cannot obtain an organization-scoped token (real token request fails); approval yields one; reject revokes; passkey enrollment is forced |
| G2.4 | Join tenant | Preview does not consume a use; approval modes `manual`, `domain_allowlist`, `auto` behave per policy; grants apply at approval |
| G2.5 | Code security | Check character catches typos; entropy and structure per section 7.6; pepper rotation; constant-time comparison (statistical timing test); byte-identical error responses; per-user, per-IP and per-code limits; expiry, rotation and max-use handling; idempotent use counting; log capture contains no code material |
| G2.6 | Privileged authentication | An OTP-only Super Admin or admin cannot reach governance endpoints; one authenticator is not enough for code generation; the step-up challenge has the RFC 9470 shape |
| G2.7 | Auth0 contract | Claims (`org_id`, role, `auth_strength`) are present after login and after refresh; the method names the Action observes are pinned; a change fails the build |
| G2.8 | Lifecycle effects | Every row of section 7.7 is executed end to end, including cascades (frozen workspace suspends tenants with `workspace_frozen`; reactivation restores only cascade-suspended tenants) |
| G2.9 | Transition authorization | Generated tests: each transition succeeds for the authorized actor, fails with 404 or 403 for others, and illegal pairs fail |
| G2.10 | Governance requests | Initiator cannot approve; one human cannot approve twice; distinct authenticators required; waits and expiry enforced with test windows; production profile lint passes minimums; cancel always allowed; every kind's effect verified |
| G2.11 | Management API hygiene | The token carries only the listed scopes; other containers cannot reach the Management API; an out-of-band role assignment is detected by the reconciliation job |
| G2.12 | Revocation hooks | Suspension removes the Auth0 membership, deletes refresh tokens, bumps `principal_version` and publishes invalidation (consumer verified in Stage 3) |

### Stage 3 — Gateway and internal trust

**Goal.** Only valid, current, correctly scoped principals reach any internal service.
**Builds.** Token verification, principal resolver, route allow-list from the matrix, context tokens with KMS-certified signer keys, revocation consumer, rate limits, idempotency, step-up handling, SSE proxy skeleton.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G3.1 | Token abuse | Real tokens: wrong audience, ID token as access token, expired, not-yet-valid, `alg=none`, HS256 confusion, wrong issuer, missing or mismatched `org_id`, tampered signature all return 401 with a uniform body |
| G3.2 | Principal resolution | Role, workspace and status come from the database; a role-claim mismatch is denied and alerted; pending users never resolve to a data-plane principal |
| G3.3 | Context tokens | Single audience, 60-second expiry, `jti` reuse rejected on state-changing calls, `pv` mismatch aborts long work; every service rejects a token minted for another audience (all service pairs tested) |
| G3.4 | Revocation SLO | With healthy pub/sub, p99 ≤ 2 s over at least 200 trials; with pub/sub killed, ≤ 5 s; SSE stream cut ≤ 2 s, fallback ≤ 15 s |
| G3.5 | Signer certificates | About one KMS call per instance per hour; minting p99 ≤ 5 ms; deny-list entry revokes within 2 s; a stolen signer key is useless after expiry |
| G3.6 | Authorization matrix | Every route × every role with real tokens returns exactly what `authz-matrix.yaml` says; any drift between OpenAPI, matrix and implementation fails |
| G3.7 | Fuzz | Schemathesis against every endpoint with each role's token: only expected 2xx and 4xx, no 5xx |
| G3.8 | Step-up | Challenge returned when authentication is stale or weak; success path; strength enforced |
| G3.9 | Limits and idempotency | Limits hold across replicas; killing Valkey falls back to a conservative local limit; replay returns the original response |
| G3.10 | Fail closed | Audit database down returns 503 for state-changing and query calls; Valkey down leaves decisions correct |

### Stage 4 — Ingestion

**Goal.** Real documents become immutable, encrypted, provably faithful chunks and consistent vectors.
**Builds.** Upload and lifecycle API, quarantine and scan, parsers, OCR with confidence, structure detection and chunker, encryption, worker pool with fair-share, `indexer`, `reconciler`, deletion and crypto-erase, holding queue, embedding pipeline, parser bake-off report.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G4.1 | Upload safety | Quarantine path works; bad checksum rejected; size and type limits; presigned URLs cannot write outside the prefix and expire within 60 s; EICAR (control) is rejected and never indexed; PDF active content is removed |
| G4.2 | Chunk fidelity | For 100% of chunks the normalized text equals the text re-extracted from the original at the stored page and offsets; no empty chunks; token bounds respected; 100% of contracts have a preamble chunk |
| G4.3 | Page and span correctness | Against at least 200 human-verified chunks across legal and medical documents, at least 98% of page ranges are exact and spans align |
| G4.4 | Structure detection | F1 against gold (clause labels from the contract dataset, SPL and JATS sections) at or above floors in `eval/floors.toml` (initial target 0.85, ratcheted) |
| G4.5 | OCR | Character error rate on rasterized real pages measured against floors; confidence correlates with errors; 100% of below-threshold pages are quarantined; a property test proves no quarantined chunk is embedded or present in Qdrant |
| G4.6 | Parser decision | Bake-off of the layout-aware parser against the baseline recorded in an ADR with metrics |
| G4.7 | Job safety | Tampered or expired envelope rejected; owner deleted before run aborts the job; re-run creates no duplicates; crash and resume at every step |
| G4.8 | Fairness | While workspace A uploads 500-page documents continuously, workspace B's ingestion p95 stays within 2× its idle baseline |
| G4.9 | No cross-workspace deduplication | The same real file in two workspaces yields distinct object keys, document keys, chunk IDs and vector IDs, different ciphertext, and statistically indistinguishable timing |
| G4.10 | Index consistency | Visibility, matter, tier or owner changes reach Qdrant within 5 s at p95; injected drift (deleted vectors, orphan vectors, altered payload) is repaired by the reconciler; zero drift afterward; orphan grace respected; scope mismatch alerts |
| G4.11 | Deletion | Deleting a document destroys its key, makes chunk text undecryptable, removes vectors and objects, and writes a tombstone; the reconciler confirms |
| G4.12 | Throughput and re-embedding | A 200-page scanned PDF completes within 10 minutes at p95 on the reference worker; embedding version recorded; a re-embed migration via a new collection and alias swap causes no downtime |

### Stage 5 — Retrieval

**Goal.** Scoped hybrid search that cannot leak across scopes, with measured quality.
**Builds.** `lmqa_vectorstore` filter builder and read-only retrieval credentials, scope resolver, wall, tier, exception and break-glass handling, hybrid query, Postgres cross-check, re-ranker and threshold calibration, retrieval ledger, large-grant path, quality baselines.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G5.1 | Vector wrapper | No query function works without a principal; every filter contains `org_id` and `workspace_id`; delete and payload-update calls also require them; the retrieval key cannot write (attempt fails) |
| G5.2 | Network policy | Only `retrieval` and `ingestion` can reach Qdrant; the Gateway and other services cannot |
| G5.3 | Retrieval quality | Recall@k, MRR and nDCG on the real evaluation sets (contract clause queries, legal retrieval benchmark subset, biomedical snippet subset) at or above `eval/floors.toml`; hybrid beats dense-only and sparse-only in the ablation |
| G5.4 | Provenance isolation | Two organizations × two admins × two tenants, each workspace with a distinct real corpus; for every query from every wrong position, no foreign chunk ID, document ID or content hash appears in any response, ledger row, cache entry, log line or export; the vector filter's result set is a superset of or equal to RLS's |
| G5.5 | Walls | A walled user receives nothing from the matter even with a grant or ownership; a wall created mid-session applies on the next request; an admin can be walled; the scope hash changes |
| G5.6 | Tiers, grants, visibility | Tier ceilings, expired grants, private versus matter documents, owner rules, admin without a session denied and with one allowed, session expiry |
| G5.7 | Emergency access | Exception created with a 60-minute expiry; tier cap 3; walled matter still denied; fifth request of the day allowed, sixth refused; admin notified; review task created; export denied |
| G5.8 | Stale index safety | Narrowing visibility denies immediately before re-indexing (mismatch counted, nothing leaked); widening shows nothing until re-indexed |
| G5.9 | Large grant sets | A tenant with 5,000 grants returns correct results through the over-fetch path; latency recorded against section 22; the admin path is unaffected |
| G5.10 | Ledger | `retrieval_records` accepts inserts only from `retrieval`; `generation` and `citation_validator` cannot write; hashes match chunk contents |
| G5.11 | Re-ranker | Threshold calibration recorded; dropped chunks stored with reasons; results deterministic for the same input |
| G5.12 | Failure modes | Qdrant down returns 503 with no fallback scan; KMS throttling uses cached keys then fails closed |

### Stage 6 — Generation

**Goal.** A bounded, injection-resistant, provider-agnostic generation path with a scoped cache.
**Builds.** Token budget, trimming, guarded compression, prompt assembly with aliases, provider client with per-organization settings, scoped cache, prompt registry, internal streaming.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G6.1 | Token budget | Property tests show the assembled prompt never exceeds the budget even for adversarial chunk sizes; counts agree with the provider's reported usage within 1 percent over 500 live calls |
| G6.2 | Trimming | Chunks are dropped whole, never cut; dropped IDs and reasons are recorded |
| G6.3 | Compression safety | 100% of critical tokens survive compression on real chunks, or compression is discarded; tables are never compressed; the validator uses original text |
| G6.4 | Prompt assembly | The captured prompt contains aliases only, never global chunk IDs; ordering rule applied; chunks delimited; instruction hierarchy present |
| G6.5 | Scoped cache | Key includes scope hash, chunk-set hash, prompt version and model; cross-scope replay never hits; permission or document change invalidates; encrypted with the cache key; off by default for medical organizations; TTL honored |
| G6.6 | Injection resistance | Real public injection strings embedded in real contract and clinical text: instruction-following rate at or below floor; output never contains content outside the ledger; the model has no tools or network access |
| G6.7 | Refusal behavior | On unanswerable real evaluation questions the refusal rate meets the floor; false refusals on answerable questions stay at or below the floor |
| G6.8 | Provider boundary | Per-organization provider settings; request capture shows no-retention settings; spend caps and circuit breaker work; timeouts and idempotent retries verified |
| G6.9 | Prompt registry | Versions hashed; prompt hash appears in the audit payload; promotion is blocked when the evaluation falls below floors |
| G6.10 | Streaming internals | Token stream reaches the Gateway; cancellation propagates to the provider; backpressure honored |

### Stage 7 — Citation validation and gated delivery

**Goal.** No unverified sentence ever reaches a client, and what was released is provably what was validated.
**Builds.** Validator checks V1 to V8, sentence segmentation, pinned entailment model with calibration, signed verdicts, stream forwarding and release in the Gateway, write-ahead audit, strip and regenerate policies, resumable stream protocol.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G7.1 | Validator tests | Unit, property (Hypothesis tag-grammar fuzz) and mutation tests; mutation score at least 80% |
| G7.2 | Segmentation | On real legal and medical text (abbreviations, decimals, section references) segmentation F1 meets the floor |
| G7.3 | Entailment calibration | On a held-out, human-labeled real set of at least 300 sentence–chunk pairs per domain, precision of "supported" is at least 0.99 at the chosen threshold; recall is reported and floored |
| G7.4 | Determinism | Identical verdicts across repeated runs and process restarts; model weights hash pinned; CPU inference |
| G7.5 | Critical tokens | Numbers, dates, amounts, dosages with units and statute references normalize and match correctly on real corpus cases |
| G7.6 | Integrity | Altering a chunk after retrieval fails V3 closed; an alias outside the ledger fails V2; the Gateway cannot change a verdict without breaking its signature (tamper test) |
| G7.7 | Gated release end to end | Across at least 1,000 live queries, every captured SSE frame sentence has a passing verdict with a matching hash; zero unverified sentences leak |
| G7.8 | Policies | `strip` and `regenerate` behave as specified; `regenerate` requires buffered mode; at most two attempts; final refusal when no verified answer exists |
| G7.9 | Write-ahead audit | Killing the audit database mid-stream halts the stream with no sentence sent after the failure; every released sentence has a prior `segment.released` event |
| G7.10 | Citation list | Built deterministically from tags; resolution of document, page, section and span matches the ledger; the side-panel endpoint re-checks RLS |
| G7.11 | Resume | `Last-Event-ID` resumes with only released and audited sentences |
| G7.12 | Latency | Time to first verified sentence and per-sentence validator time meet section 22 budgets |

### Stage 8 — Frontend

**Goal.** A secure, accessible interface whose routing and streaming behave exactly as designed.
**Builds.** Next.js 16 application, `proxy.ts`, Auth0 SDK integration, onboarding, chat with citation panel, library with OCR review, Manage Admins, Manage Tenants, governance center, walls, review queue, audit, account pages, generated API client, CSP with nonces.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G8.1 | Route matrix | Playwright with real Auth0 tokens: every route × role returns what section 17.1 says; forbidden routes return 404; pending and suspended users are blocked |
| G8.2 | Onboarding e2e | All three paths and the approvals work; fragment-based invite codes are removed from history and never appear in network logs except the POST body |
| G8.3 | Management flows | Manage Admins, Manage Tenants, governance, walls and review flows work end to end; secrets render once and are cleared after close |
| G8.4 | Streaming torture | The real stream, sliced at every byte boundary by a network proxy, renders identically; event ordering and reconnect-and-resume verified |
| G8.5 | No tokens in the browser | Inspection of storage, cookies and response bodies finds only an opaque httpOnly session ID; deleting the server-side session ends access at once |
| G8.6 | CSP and sanitizing | Nonce-based strict CSP on every response; zero console violations across e2e; hostile markup from public XSS corpora embedded in real documents renders inert |
| G8.7 | Accessibility | axe finds zero serious or critical issues; keyboard-only flows pass; WCAG 2.2 AA checklist complete |
| G8.8 | Static checks | ESLint zero warnings, `tsc --noEmit`, Vitest, bundle budget, generated client matches the contracts |
| G8.9 | Citation panel | Highlighted spans equal the chunk spans; stripped-sentence marker shown |
| G8.10 | Responsiveness | Budgets for first meaningful paint and first streamed sentence met on reference hardware |

### Stage 9 — Governance, audit, operators and lifecycle

**Goal.** The system can be governed, audited and recovered, and destroyed safely, without trusting any one person.
**Builds.** Audit service, anchoring and verifier, alerting, quotas and noisy-neighbor controls, retention and legal hold, break-glass and emergency flows end to end, operator plane and JIT, KeyGuard workflow, organization and workspace destruction, successor transfer, owner recovery, backups and DR.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G9.1 | Audit verification | Chain, checkpoints and anchors verify against the real Object Lock bucket; tampering is detected; deleting an anchor object is refused |
| G9.2 | Audit sealing | Writers cannot decrypt payloads (attempt fails); the `audit` service can; destroying a month's key makes payloads unreadable while the chain still verifies |
| G9.3 | Alert drills | Every alert in section 13.6 is triggered for real and delivered to a real on-call channel within its target |
| G9.4 | Quotas and noisy neighbor | Hierarchical limits enforced; workspace A flooding does not push workspace B past its latency target; circuit breaker trips and recovers |
| G9.5 | Retention and legal hold | A hold blocks deletion at document, workspace and organization level; deletion proceeds when retention ends; tombstones recorded |
| G9.6 | Destruction drill | Full ritual in a throwaway organization on real KMS with the `drill` tag: two approvers, waits, seal, scheduled deletion, verification, restore from backup with tombstone replay stays unreadable; cancel and restore paths tested at every step |
| G9.7 | Operator plane | JIT lifecycle (request, approve, expire, revoke); content access needs the workspace admin; `ops_metadata_ro` cannot read content tables; operators hold no standing credentials, cannot sign tokens, cannot approve their own access; every grant appears in the customer's audit; expiry stops access within the SLO |
| G9.8 | Break-glass and emergency | Admin private-read session end to end, visible to the affected tenant; emergency reviews and the 48-hour and 72-hour alerts fire |
| G9.9 | State-machine coverage | Generated API-level tests for governance, access-session, workspace and organization transitions pass with distinct real approvers |
| G9.10 | Disaster recovery | PostgreSQL point-in-time restore, Qdrant snapshot restore and object recovery; reconciler repairs; measured recovery time and point meet section 22 targets |
| G9.11 | Successor and recovery | `successor_transfer` and `owner_recovery` run end to end with notices, cooling-off and flag resets |
| G9.12 | Key alerts and escrow | A scheduled-deletion event pages within 60 seconds and is auto-cancelled when unapproved; custodian approvals work; an escrow restore drill succeeds |

### Stage 10 — System verification

**Goal.** Prove the whole system, at scale, under failure, against the evaluation floors.
**Builds.** Isolation suite as a required check, fuzz job, load and chaos suites, full evaluation harness in CI, security scans, SBOM and signing, performance report, penetration-test package.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G10.1 | Cumulative re-run | Gates G0 to G9 pass again on a clean environment, twice |
| G10.2 | Isolation suite | Every group in section 21 passes as a required check; provenance scan finds zero leaks in every output channel |
| G10.3 | Fuzz job | Mutated IDs, headers and bodies against every endpoint with each role's token: 200 only for in-scope calls, 404 or 403 otherwise |
| G10.4 | Load | k6 profiles meet section 22 budgets at the target scale built by replicating real documents |
| G10.5 | Chaos | Killing each service, Valkey, Qdrant slowness, KMS throttling, Auth0 unreachable and audit unavailable produce the fail-closed behavior in section 10.4 with no data exposure |
| G10.6 | Evaluation floors | Retrieval, refusal, validator precision and end-to-end citation pass rate meet floors on the full evaluation sets |
| G10.7 | Security scans | Trivy and Grype image scans, Semgrep, dependency audit clean of unresolved critical and high findings; SBOM generated and signed |
| G10.8 | Performance specifics | Large grant sets, KMS quota use with the DEK cache, and RLS grant-check indexing results recorded in `docs/perf-report.md` and within budget |
| G10.9 | Supply chain | Reproducible builds; images signed; provenance attestations verified at deploy |
| G10.10 | Review package | Architecture, data-flow diagrams, test accounts and counsel question list complete for the external reviewers |

### Stage 11 — Production readiness

**Goal.** Go live safely. Several gates here are external by nature and are tracked as evidence, not as code.
**Builds.** Production infrastructure from code (VPC, Kubernetes, managed PostgreSQL 18, Qdrant cluster, S3, KMS with vault account, production Auth0 tenant), staging and production overlays, canary deployment for generation, runbooks and on-call, pilot plan.

| Gate | Check | Pass criterion |
| --- | --- | --- |
| G11.1 | Production configuration | `tofu plan` clean; policy lint passes on the production profile (waiting windows, MFA and passkey settings, KMS windows, flags) |
| G11.2 | Penetration test | External test completed; no open critical or high findings; medium findings triaged with dates |
| G11.3 | Security architect review | Review completed; findings closed or accepted by a named owner |
| G11.4 | Counsel sign-off | HIPAA, privilege and ethical-wall rules, retention and breach-notification positions recorded |
| G11.5 | Vendor agreements | Auth0 BAA (plan and add-on), BAAs or no-retention terms for LLM, embedding, OCR and hosting providers, data processing terms executed |
| G11.6 | DR and shred drills | Disaster-recovery drill and restore-and-shred drill passed in a production-like environment |
| G11.7 | Canary | Generation canary deployment proven to roll back on a drop in live citation-validation pass rate |
| G11.8 | Operator readiness | On-call rota, runbooks drilled, operator background checks and training, first access review done |
| G11.9 | Pilot | A pilot customer under a signed BAA with data minimization and agreed success criteria; real customer data enters only after G11.4 and G11.5 |
| G11.10 | Go-live checklist | Signed by named owners for security, privacy, engineering and operations |

## 21. Isolation and verification suite

The suite is a merge gate (`isolation` marker), built from real organizations created through the product's own flows. Two organizations each have two admins and two tenants, and every workspace holds a distinct real corpus; leaks are detected by **provenance**: every chunk, document and object carries a source SHA-256 and IDs, and the scanner searches every response, SSE frame, ledger row, cache entry, log line, audit export, object URL and error body of every wrong-position caller for any identifier or distinctive content hash from another scope. A hit anywhere fails the build. Because the corpora are real public documents, no fabricated canary text is needed; where a document must be unmistakable, the scanner uses its content hash.

| Group | Assertion | Stage |
| --- | --- | --- |
| Admin to admin | Admin A cannot list, read, query or download anything in workspace B, by ID guess or by search | 5 |
| Super Admin boundary | 404 on every tenant route; direct SQL as `super_admin` returns zero rows from documents, chunks, tenant memberships, walls and audit payloads | 1, 3 |
| Tenant to tenant | A tenant sees only own private documents and granted matter documents; other users' private documents inside a granted matter stay hidden; grant removal applies on the next request | 5 |
| Cross-organization | No token, ID or code from organization 1 works in organization 2 | 3, 5 |
| Fail closed | No context returns zero rows; a vector search without a filter cannot be issued; services refuse to boot when the self-test fails | 1, 5 |
| Token abuse | Wrong audience, issuer, expired, `alg=none`, ID token as access token, mismatched `org_id` rejected | 3 |
| Revocation | A suspended user's valid token is rejected within SLO; an open stream is cut within SLO | 3 |
| Codes | Wrong, expired, rotated and over-used codes give identical responses; limits trigger; codes never appear in logs or responses | 2 |
| Escalation | A tenant cannot assign `admin`, change its role, approve itself or call identity endpoints for another scope | 2, 3 |
| Walls | A wall beats grants, ownership and emergency access; effect on the next request | 5 |
| Emergency and break-glass | Time-boxed, tier-capped, audited, reviewed; ends on schedule | 5, 9 |
| Cache | A cached answer built for a broad scope is never served to a narrower one; deletions and permission changes invalidate | 6 |
| Async | Tampered or expired envelope rejected; deleting the owner before the run aborts it | 4 |
| Index consistency | Stale payloads cannot leak; reconciler repairs injected drift | 4, 5 |
| Audit | UPDATE and DELETE on audit tables fail; a broken chain is detected; writers cannot decrypt payloads | 1, 9 |
| Gated release | No unverified sentence reaches a client across live runs | 7 |
| Noisy neighbor | One workspace flooding uploads and queries does not push another past its latency target | 4, 9 |
| Private documents | An admin cannot read a tenant's private documents unless the flag is on and a session is active | 5, 9 |
| Onboarding tokens | An organization-less token is rejected by the main API; a pending user cannot obtain an organization-scoped token | 2, 3 |
| Aggregates | `super_admin` reads `workspace_usage` but gets zero rows from tenant-level tables | 1 |
| Successor transfer | Cooling-off enforced, notices sent, flag reset | 9 |
| Key shredding | After a test organization's key is destroyed, restored backups cannot be decrypted while other organizations are unaffected; document-level deletion stays deleted after restore | 1, 9 |
| Key guardrails | No ordinary principal can schedule key deletion; an unapproved scheduling is auto-cancelled | 1, 9 |
| Operators | Operators cannot read content without approval; access expires on time | 9 |
| Contract | Auth0 claim shape and method names unchanged | 2 |

A periodic fuzz job mutates IDs, headers and bodies against every endpoint using each role's token, expecting 200 only for in-scope calls and 404 or 403 otherwise.

## 22. Performance and capacity plan

Performance cannot be proven by a document. This section turns the known risks into **budgets to validate**, with the stage that measures each. Every number is a target to be confirmed or changed by evidence recorded in `docs/perf-report.md`; changing one needs an ADR.

| Risk | Budget (target to validate) | Measured in | Mitigation if missed |
| --- | --- | --- | --- |
| Very large grant sets make large vector filters | Retrieval stage p95 ≤ 800 ms for a tenant with 5,000 grants at 1,000,000 chunks in the workspace; inline filter up to 256 matters | G5.9, G10.8 | Over-fetch and cross-check path; matter grouping; collection per workspace for such tenants |
| RLS grant, wall and exception lookups | Policy overhead ≤ 20% over an unconstrained baseline at 10,000 grants per user | G1.4 extension, G10.8 | Index changes; `policy_helper` function plan caching; denormalized effective-scope table maintained by the identity service |
| KMS request quotas with per-organization keys | KMS use ≤ 5% of regional quota at peak with the workspace key cache (15-minute TTL); calls ≈ (instances × active workspaces) per TTL | G1.10, G10.8 | Longer TTL within policy; per-instance sharing; request quota increase; fewer unwrap calls via data-key caching |
| Context-token signing | Minting p99 ≤ 5 ms; KMS signing calls ≈ 1 per instance per hour | G3.5 | Already designed around the problem (section 9.1) |
| Audit chain lock contention | 200 audit writes per second per workspace chain sustained | G10.4 | Shard chains per workspace |
| Query end to end | p95 time to first verified sentence ≤ 6 s (dominated by the LLM); validator per sentence p95 ≤ 150 ms on CPU | G7.12, G10.4 | Smaller entailment model, batching sentences, parallel validation |
| Ingestion | 200-page scanned PDF ≤ 10 minutes p95; fair-share under flood (G4.8) | G4.12, G10.4 | More workers; GPU OCR |
| Revocation | See section 8.6 | G3.4 | n/a |
| Disaster recovery | RPO ≤ 5 minutes (point-in-time recovery and WAL archiving); RTO ≤ 4 hours for the data plane | G9.10, G11.6 | Replicas; warm standby |

Target scale for Stage 10: 100 organizations × 5 workspaces × 20 tenants, 50 million chunks in aggregate, built by replicating real documents (R8).

## 23. Threat model

| Threat | Scenario | Controls |
| --- | --- | --- |
| Leaked Organization Code | Pasted into a chat or forwarded | Pending approval, expiry and use cap, hashed storage, instant rotation, new-geography alert, email-bound invites |
| Leaked Admin Code | Outsiders request tenant access | Manual approval by default, domain allow-list option, rotation, use cap, alerts |
| Code guessing | Scripted attempts | Secret portions of 275 and 115 bits, per-user, IP and code limits, identical errors, bot detection |
| Role escalation | Client sends `role=admin` or edits its profile | Role derived from proof and database, immutable roles, Auth0 roles assigned only by the identity service |
| Cross-workspace read (IDOR) | Admin A guesses a document ID from workspace B | Opaque UUIDs, scoped repositories, RLS, 404, provenance tests |
| Super Admin overreach | Owner or a compromised owner session reads tenant content | No route, no service path, no policy, sealed audit payloads, passkey-only privileged login |
| Stolen session or token | XSS or malware on an admin laptop | Tokens never reach the browser, server-side sessions that can be revoked, nonce CSP, 10-minute access tokens, refresh rotation, passkeys, step-up |
| Platform insider | Our engineer browses data | No standing access, JIT with customer approval, per-organization keys, recorded access visible to customers |
| Key destruction (accidental or malicious) | Someone schedules deletion of an organization key | Deny policies, two roles only, two-person workflow, 30-day windows, replica and escrow, 60-second paging, auto-cancel responder |
| Cache leakage | Cached answer served across scopes | Cache after retrieval, chunk-set and scope-hashed keys, validator re-check, per-workspace encryption |
| Vector filter bug | A missing filter returns another workspace's vectors | Wrapper without unfiltered variant, Postgres cross-check as final authority, mismatch alerting, collection-per-workspace tier |
| Stale index | Visibility narrowed but vector payload lags | Postgres authority, outbox, reconciler, safe-direction behavior |
| Noisy neighbor | Huge uploads or query floods | Hierarchical quotas, fair-share queues, concurrency caps, spend alerts |
| Prompt injection | Instructions planted in a shared document | Delimited chunks, no tools, aliases, validator, sanitized output |
| Unverified output | A hallucinated claim reaches a user | Sentence-gated release, signed verdicts, write-ahead audit |
| Management API compromise | Attacker uses the M2M credential to create admins | Credential held by identity only, minimal scopes, egress policy, reconciliation alerts |
| Account takeover | Attacker registers with a victim's email | Verified email, MFA, no automatic linking, SSO enforcement, passkeys for privileged roles |
| Recovery downgrade | Attacker uses a weaker recovery path to take a privileged account | No self-service downgrade; 72-hour operator-verified recovery with notices and a veto |
| State-machine bypass | Application bug skips an approval state | Database transition tables and triggers; generated tests |
| Orphaned data | An admin leaves and tenants are stranded | Freeze and successor workflow, sealing, holding queue |
| Audit tampering | Privileged user edits history | Insert-only function, hash chain, hourly WORM anchor, sealed payloads |
| Replayed onboarding | Double submit burns code uses | Idempotency keys; use counted when a membership is created |
| Secret leakage in logs | Codes or PHI in logs | Fragment links, redaction, allow-listed log fields, log-scan tests |
| Signing key compromise | Attacker forges principals | KMS trust root, one-hour signer certificates, deny-list, mTLS, alert on tokens from outside the Gateway |
| IdP auto-membership | A customer SSO silently adds every employee | Auto-membership off, membership only by the identity service, subject matching |
| Backup resurrection | Deleted data returns from a backup | Per-organization CMK for organization deletion; tombstone ledger replay and 35-day backup expiry for smaller scopes |
| Cross-tenant side channels | Deduplication, timing or error differences | No cross-workspace deduplication or shared caches, uniform errors, scope-hashed keys |
| Dishonest Super Admin | Owner appoints an identity they control | Two-person transfer, cooling-off, notices, non-suppressible audit, owner-linked disclosure |
| Emergency-access abuse | A clinician invokes override routinely | Reason codes, limits per day, immediate notification, mandatory review, alerts |
| Ethical-wall bypass | A walled lawyer reads through cache, ownership or admin role | Wall precedence in policy, filter and scope hash; tests |
| Test-environment data leakage | Real PHI used in dev or CI | R4, public corpus only, egress rules, manifest review |
| Dependency compromise | Malicious package or tool release | Pinned versions and digests, cooldown, SBOM, signed attestations, scanning |

## 24. Decisions and open items

"Decided" means the design adopts the choice and the stage gates test it. "Confirm" means a person or a vendor must confirm it before the stage that depends on it. Architecture decision records `docs/adr/0001` to `0012` capture the reasoning: 0001 service split, 0002 tenancy model, 0003 Auth0 authenticates and PostgreSQL authorizes, 0004 vector isolation and pgvector alternative, 0005 key hierarchy and KeyGuard, 0006 delivery and validator, 0007 real data and no mocks, 0008 context-token certificates, 0009 audit sealing, 0010 object store and encryption, 0011 queue choice, 0012 toolchain.

| ID | Decision | Status | Section |
| --- | --- | --- | --- |
| D1 | A Super Admin who needs document work registers a second identity as an owner-linked admin, with disclosure to tenants | Decided | 5.9 |
| D2 | Admins cannot read tenants' private documents by default; a governed flag plus break-glass sessions enable it | Decided | 5.8 |
| D3 | Lost Super Admin: co-owner, otherwise `owner_recovery` with a 72-hour wait and a veto | Decided | 6.7, 14.6 |
| D4 | Codes are shown once and rotated, never re-displayed | Decided | 7.6 |
| D5 | Pooled infrastructure with RLS and per-organization keys by default; silo tier on contract | Decided | 10.10 |
| D6 | Tenant approval defaults to manual | Decided | 7.4 |
| D7 | One membership per user in v1; schema ready for more | Decided | 5.1 |
| D8 | Auth0 plan, region and BAA add-on for medical deployments | **Confirm** before any PHI | 8.1 |
| D9 | Organization creation is operator-approved in production, open in dev and demo | Decided | 7.2 |
| D10 | Audit and document retention defaults per jurisdiction (six-year baseline for medical documentation) | **Confirm** with counsel | 13.8 |
| D11 | Removed admin: successor transfer with second approval; seal after 30 days; destroy after retention | Decided | 7.8 |
| D12 | Semantic cache is off by default for medical organizations | Decided | 10.7 |
| D13 | Passkeys or WebAuthn mandatory for Super Admins and admins; two authenticators for governance | Decided | 8.4 |
| D14 | Co-owner recommended within 14 days; operator-verified fallback otherwise | Decided | 7.5 |
| D15 | Sentence-gated delivery by default; buffered with regenerate; no provisional mode; thin SSE client, no Vercel AI SDK | Decided | 11.6, 17.3 |
| D16 | Pooled vector collection behind a filtering wrapper with Postgres as authority; collection-per-workspace tier for high assurance | Decided | 10.5 |
| D17 | LLM and embedding provider boundary per organization; BAA and no retention by default for medical; self-hosted option by Stage 11. Open: whether self-hosting should be the default | **Confirm** | 11.8 |
| D18 | Procrastinate (PostgreSQL-backed) for jobs with direct worker connections; Celery as fallback | Decided pending G0.13 | 4.5, 10.3 |
| D19 | SeaweedFS for the local object store, subject to the capability probe | Decided pending G0.4 | 4.5 |
| D20 | Valkey instead of Redis 8 | Decided | 4.5 |
| D21 | Python 3.14, `uv`, `ruff`, `pytest`, `pyright` | Decided | 4.5, 19 |
| D22 | PostgreSQL 18; PostgreSQL 19 after GA plus its first minor | Decided | 4.5 |
| D23 | AWS as the reference cloud (KMS, S3, EKS); OpenBao for fast shredding tests | Decided; **confirm** the cloud | 12 |
| D24 | Operators use a separate identity provider and JIT access | Decided | 14 |
| D25 | Emergency access only in medical or mixed workspaces, opt-in per workspace | Decided; counsel confirms | 5.7 |
| D26 | Walls beat all grants; lifting needs two people | Decided; counsel confirms | 5.6 |
| D27 | Public real corpus; credentialed medical data only in an opt-in self-hosted lane | Decided | 19.1, App. B |
| D28 | No mocks or fake data anywhere; negative controls are labeled instruments | Decided | 19.1 |
| D29 | Context tokens signed by KMS-certified ephemeral keys | Decided | 9.1 |
| D30 | Next.js 16 container deployment with `@auth0/nextjs-auth0` v4, `proxy.ts` and a Valkey-backed server-side session store | Decided | 4.5, 8.3, 17 |
| D31 | Sealed audit payloads and a separate `audit` service | Decided | 13.2 |
| D32 | Parser stack chosen by the Stage 4 bake-off | Pending G4.6 | 11.1 |

## 25. Residual risks, assumptions and external validation

### 25.1 Residual risks

No multi-tenant system is foolproof, and this one does not claim to be. The goal is narrower and testable: one mistake in one layer must not expose another scope's data, and any breach must be detected, bounded and provable.

| Residual risk | Why it remains | How it is bounded |
| --- | --- | --- |
| Dishonest Super Admin | The owner decides who the admins are; an owner-linked admin may be the same human | Two-person transfer, cooling-off, tenant notice, non-suppressible audit, owner-linked disclosure, contract terms |
| Collusion of two key custodians or custodian plus owner | Two-person rules assume two honest people | Separation of roles and employers, 60-day minimum windows, customer-side approvers, alerts, escrow and replica, background checks |
| Compromised root of trust (PostgreSQL superuser, KMS administrator, trust-root key) | Every system trusts something at the bottom | Separation of duties, hardware-backed keys, no standing human access, key-use alerts, annual penetration test |
| Third-party processors (Auth0, LLM, embedding, OCR, hosting) | Data crosses the boundary by design | BAAs and no-retention terms, per-organization provider settings, self-hosted option |
| Wrong approval by a person | An approver accepts an impostor with a leaked code | Verified identity shown at approval, domain allow-list, notifications, quarterly access attestation |
| Authorized user misuse | A valid user copies data they may lawfully read | Rate limits, export step-up, anomaly alerts, full audit |
| Auth0 outage or misconfiguration | Login depends on a third party | Sessions end at their limits, system fails closed, configuration as code and drift-tested |
| Model error | An answer can be wrong even when cited | Validator, human-review workflow, disclaimers; outside the scope of tenancy |
| Entailment model error | A subtle negation can pass | Calibrated precision floor, human review, evaluation monitoring |
| Backup window for small-scope deletions | A deleted document's wrapped key exists in backups until they expire | 35-day maximum backup life and tombstone replay on restore |
| Real PHI gap in testing | Public data does not include real SOAP notes | Credentialed lane and a pilot under a BAA |

### 25.2 Trust assumptions

1. PostgreSQL, Valkey, the vector database, the object store and KMS are not reachable from the public internet, and services run as non-root under network policies.
2. CI runs the isolation suite on every merge and nobody can bypass the gatekeeper.
3. Auth0 enforces MFA, passkeys and organization membership as configured.
4. Clocks are synchronized, since token lifetimes are measured in seconds.
5. The cloud provider's KMS and Object Lock behave as documented.

Three recurring controls keep these honest: a quarterly access attestation (each admin reviews tenants, the Super Admin reviews admins, operators review their own access, unattested accounts are flagged), an annual external penetration test, and an annual restore-and-shred drill.

### 25.3 What editing cannot close

| Item | Why a document cannot close it | Closed by | Owner |
| --- | --- | --- | --- |
| Performance under load: large grant sets, KMS quotas and data-key caching, RLS indexing, audit lock | Only measurement shows the numbers | G5.9, G10.4, G10.8, `docs/perf-report.md` | Engineering lead |
| Nothing is built yet; every guarantee is a design claim | Needs code and a passing isolation suite | All gates, especially G10.2 | Engineering lead |
| Penetration test | Needs an independent tester | G11.2 | Security |
| Security architect review | Needs an independent reviewer | G11.3 | Security |
| Counsel on HIPAA, privilege, ethical walls, retention, breach notification | Legal judgment | G11.4 | Privacy and legal |
| Auth0 plan, BAA and add-ons | Contract and pricing | G11.5, D8 | Procurement and privacy |
| LLM, embedding, OCR and hosting provider agreements | Contract | G11.5 | Procurement and privacy |
| Qdrant features at the pinned version (tenant promotion, JWT scope, audit logs) | Version-specific vendor behavior | G5.1, G5.2 plus a pin-time check | Engineering lead |
| Corpus licences | Legal reading of each licence | G0.8 | Privacy and legal |
| Disaster recovery and key-escrow drills | Operational practice | G9.10, G9.12, G11.6 | Operations |

## Appendix A — Defect register

Defects found while reconciling the four source documents (DEF-01 to DEF-48) and during the second review pass (DEF-49 to DEF-64), with the section of this report that resolves each. "Item n" refers to your review list.

| ID | Found in | Defect | Resolution | § |
| --- | --- | --- | --- | --- |
| DEF-01 | v2.1 §6.1 to §6.2 | Vector database counted as "final authority"; Qdrant's JWT access control is collection-level and does not enforce payload filters in a shared collection | PostgreSQL is the only final authority; filtering wrapper; collection-per-workspace tier | 10.1, 10.5 |
| DEF-02 | v2.1 §6.3 | Tenant policy lacked a visibility check, exposing other users' private documents inside a granted matter (same flaw in the vector filter) | Rule 5 of the access decision requires `visibility = matter`; CHECK constraint; oracle test | 5.4, G1.4 |
| DEF-03 | v2.1 §7 | Workspace and audit sub-keys derived by HKDF cannot be destroyed independently of the parent | Independent random keys, wrapped | 12.1 |
| DEF-04 | v2.1 §7, §9 | Claim that per-organization keys make restored backups unreadable holds only for organization deletion | Tombstone ledger and 35-day backup life for smaller scopes | 12.9 |
| DEF-05 | Enterprise, Deep-dive, v2.1 | Raw tokens streamed to the browser "marked unverified" contradicts the hard gate and cannot support regeneration | Sentence-gated and buffered delivery; no provisional mode | 11.6 |
| DEF-06 | Enterprise, v2.1 §6.5, §13.2 | Cache owner unclear (Gateway or Generation); a hit skipped retrieval and its filter | Cache in Generation after retrieval, keyed by chunk-set hash | 10.7 |
| DEF-07 | v2.1 §5.4, §14 | Revocation timings inconsistent (2 s, 5 s, 15 s) | One SLO table with targets and hard bounds | 8.6 |
| DEF-08 | v2.1 §8.4 | "Any RLS denial" alert is infeasible because RLS silently filters SELECT rows | Detection signals that exist | 13.6 |
| DEF-09 | v2.1 §2.1, §5.2 | Ambiguous whether role comes from the token or the database | Database only; token role is advisory; mismatch denied | 8.3 |
| DEF-10 | Build, v2.1 §5.8, §7 | Mock IdP, file-backed KMS, shared internal key, mockable LLM client and demo seed conflict with the real-data, Auth0 requirement and cannot test key deletion | Real Auth0 and KMS, per-service credentials, no-mocks rule | 9.2, 12.10, 19.1 |
| DEF-11 | v2.1 §4.5 | Entropy claim ignored the plaintext lookup ID; trailing characters displayed | Secret entropy 275 and 115 bits; no trailing characters shown | 7.6 |
| DEF-12 | v2.1 §10 | Admin told to reassign removed tenants' private documents "by ID" without any policy letting them list them | Metadata-only holding queue and governed reassignment | 7.7 |
| DEF-13 | v2.1 D1 | Second identity for a Super Admin bypasses self-approval and content boundaries at the human level | Owner-linked disclosure, co-owner approval, residual risk stated | 5.9 |
| DEF-14 | Build, v2.1 §6.4 | Where chunk text lives and how the re-ranker gets it was inconsistent | Vectors carry IDs and filter fields; text from PostgreSQL under RLS | 10.5, 11.3 |
| DEF-15 | Enterprise, Build | "Deterministic, non-LLM" validator undefined; validator trusted a chunk set supplied by the orchestrator | Determinism defined; retrieval ledger; signed verdicts | 9.4, 11.6 |
| DEF-16 | v2.1 §8.1 | Monthly partition retention would break hash-chain verification | Checkpoint records | 13.3 |
| DEF-17 | v2.1 §6.4 | "Allowed confidentiality tiers" had no source of truth | Grant `max_tier` | 5.5 |
| DEF-18 | v2.1 §7 (item 1) | One accidental or malicious key deletion is permanent | Guardrails, two-person approval, windows, escrow and replica | 12.5 to 12.8 |
| DEF-19 | v2.1 §4.2 | Said each organization has its own Auth0 roles; roles are tenant-wide | Roles defined once, assigned per membership | 8.1 |
| DEF-20 | v2.1 §12.2 (item 2) | API table lacked first code generation, successor transfer, break-glass, workspace state changes | Complete API surface and governance requests | 15 |
| DEF-21 | v2.1 §4.6 (item 4) | Only membership had a state machine | State machines for all lifecycles, as data | 6 |
| DEF-22 | v2.1 §5.5 (item 6) | Privileged sign-in strength undefined; one approver for organization deletion | Passkeys, two authenticators, two-person deletion | 8.4, 12.6 |
| DEF-23 | v2.1 §6.2 | Gateway minted presigned URLs, giving it storage credentials | Ingestion owns uploads and downloads | 11.1 |
| DEF-24 | v2.1 (item 7) | No ethical walls or emergency access | Walls with precedence; emergency access | 5.6, 5.7 |
| DEF-25 | v2.1 (item 3) | Operator access mentioned, never specified | Operator plane | 14 |
| DEF-26 | v2.1 §5.6 | Signing context tokens by KMS call is a latency and quota bottleneck | KMS-certified ephemeral signer keys | 9.1 |
| DEF-27 | v2.1 §7, §8 | One symmetric audit key available to every writer | Public-key sealed payloads; `audit` service decrypts | 13.2 |
| DEF-28 | Enterprise | "Redis never holds PHI" contradicted a semantic cache of answers | Encrypted, short-lived, off by default for medical | 10.7 |
| DEF-29 | v2.1 §4.2 | Organization Code generated in the saga would be held in plaintext until shown | Generated on demand after two authenticators | 7.2 |
| DEF-30 | v2.1 (document visibility rules) | A flag alone gave standing admin access while claiming per-access break-glass | Flag plus active session in the policy | 5.8 |
| DEF-31 | Build §9 | Build order put the UI before authorization and isolation | Stage order | 20 |
| DEF-32 | Build, Enterprise | Outdated choices: `middleware.ts`, NextAuth only, MinIO community, Arq, Redis licensing, older runtimes | Verified current stack | 4.5 |
| DEF-33 | Deep-dive | Low-confidence OCR chunks were flagged but still embedded | Quarantine, never embedded | 11.1 |
| DEF-34 | Deep-dive | Text before the first heading (parties, effective date) was dropped | Preamble chunk | 11.1 |
| DEF-35 | Enterprise, v2.1 | Model asked to produce the citation list, which it can get wrong | Validator builds it | 11.5 |
| DEF-36 | Deep-dive | SSE client parsed each network chunk, breaking frames split across chunks | Buffered parser and byte-boundary test | 17.3 |
| DEF-37 | Deep-dive | Matter ID and tenant taken from the request or user object | Derived from principal and database | 3.1, 8.3 |
| DEF-38 | Deep-dive | Audit written fire-and-forget | Write-ahead, fail closed | 11.6 |
| DEF-39 | Deep-dive | BFF minted its own service JWT from the session | Single minting path at the Gateway | 9.1 |
| DEF-40 | Deep-dive | Chunks stored only the starting page | Page ranges and spans | 11.2 |
| DEF-41 | v2.1 §3.3 | Super Admin policy set omitted own and co-owner memberships and governance requests | Added | 5.3 |
| DEF-42 | v2.1 | No component owned audit reads, search and anchoring | `audit` service | 4.2 |
| DEF-43 | v2.1 §8.1 | Per-chain audit lock throughput unaddressed | Shard option and budget | 13.3, 22 |
| DEF-44 | v2.1 §6.3 | Policies reading other RLS tables under FORCE would deny or recurse | Helper functions with role-targeted policies | 10.3 |
| DEF-45 | Build §5 | "Insert-only table" claimed to prove the audit pattern with no tamper evidence | Hash chain and WORM anchor from the start | 13.3 |
| DEF-46 | Build CI | Citation evaluation ran only for prompt or generation changes | Cumulative gates; evaluation floors checked on every relevant stage | 19.6, G5.3, G10.6 |
| DEF-47 | Enterprise | pgvector option not reconciled with the isolation model | Evaluated in ADR 0004; Qdrant default | 10.5 |
| DEF-48 | Enterprise, v2.1 | Retention date shown in the library but missing from the model; no legal hold on documents | `retention_until` and `legal_hold` fields | 16.2 |

| DEF-49 | v3.0 §4.2, §9.1 | The Gateway's database role could read only `principal_v`, yet it had to put `scope_hash` and `scope_version` into every context token | `principal_v` exposes both, maintained by triggers on grants, walls, exceptions, sessions and flags | 9.1, 10.3, 16.2 |
| DEF-50 | v3.0 §4.4, §11.6 | The Gateway split the stream into sentences while the Validator defined sentence boundaries: two segmenters, and logic in the Gateway | The Validator owns segmentation and returns signed verdicts carrying the sentence text | 4.4, 11.6 |
| DEF-51 | v3.0 §11.6 (V7) | "Refusal must be the only content" contradicted partial answers and could not be checked during sentence-gated release | V7 rewritten as refusal consistency | 11.6 |
| DEF-52 | v3.0 §10.3 | `current_setting(..., true)` returns an empty string, not NULL, on a pooled connection after an earlier transaction-local setting; the UUID cast then errors instead of matching nothing | `NULLIF(current_setting(...), '')` in every policy; test on a reused pooled connection | 10.3, G1.3 |
| DEF-53 | v3.0 §4.5, §9.3 | Procrastinate's `LISTEN`/`NOTIFY` and advisory locks do not work through a transaction-pooling PgBouncer; transactional enqueue is not automatic; prepared statements need pooler support | Connection routing rules, SQL-level enqueue, direct worker connections, queue spike gate | 4.5, 9.3, 10.3, G0.13 |
| DEF-54 | v3.0 §7.8 | A successor could be "an active admin elsewhere", contradicting one membership per user and one workspace per admin | Successor is a new identity joined by a `successor` invite bound to the frozen workspace | 7.8 |
| DEF-55 | v3.0 §5.6, §10.6 | Wall creation was described as triggering vector payload updates; walls are evaluated at query time | Corrected; nothing to re-index | 5.6, 10.6 |
| DEF-56 | v3.0 §12.6, §12.7 | Sealing used an undefined "seal key" separate from the escrow key; the destruction ritual scheduled only the CMK, leaving the escrow key and replica outside the window | One escrow CMK serves escrow and sealing; replica, CMK and escrow key are scheduled together | 12.6, 12.7 |
| DEF-57 | v3.0 §20 (G0.7, G2.x, G3.x) | Real Auth0 logins in Stages 0 to 7 need a relying party, but the frontend arrives in Stage 8 | `tools/auth_harness`, a minimal real client registered in the tenant | 18, G0.7 |
| DEF-58 | v3.0 §8.3, §17.3 | "Tokens stay server-side" contradicted the SDK's default stateless cookie session, which puts encrypted tokens in the browser and cannot be revoked server-side | Valkey-backed server-side session store with an opaque ID | 8.3, 17.3 |
| DEF-59 | v3.0 §5.4, §6.4 | Access rule 1 ignored organization state; what a Super Admin of a `pending` organization may do was undefined | Rule 1 covers the organization; pending capabilities defined | 5.4, 6.4, 15.3 |
| DEF-60 | v3.0 §6.7 | `owner_recovery` needed three distinct operators but the table implied two | Initiator and two approvers named separately | 6.7 |
| DEF-61 | v3.0 §17.3 | Nonce-based CSP forces dynamic rendering in Next.js; the cost was unstated | Stated and accepted | 17.3 |
| DEF-62 | v3.0 §11.6 | Stream resumption by `Last-Event-ID` had no stored events to resume from | Encrypted 10-minute resume buffer | 11.6 |
| DEF-63 | v3.0 §9.4 | Ledger rows were scoped to the workspace only, so any user in a workspace could read another user's request record | Reads also scoped to the requesting `user_id` | 9.4 |
| DEF-64 | v3.0 (cross-references) | Mis-cited sections and defects (key deletion pointed to §12.2, code generation cited DEF-11 instead of DEF-29) | Corrected; the validation script now checks every reference | 7.2, 10.6 |

## Appendix B — Real-data corpus and evaluation sources

`corpus/manifest.toml` is the only fixture source. Every item records `id`, `title`, `source_url`, `license`, `retrieved_at`, `sha256`, `bytes`, `format`, `domain`, `kind`, `pages`, `scanned`, `allowed_use` (`commercial`, `internal_eval_only`, `excluded`) and notes. The loader verifies hashes; the gate fails on any mismatch or missing licence. English-language documents only in v1.

| Domain | Candidate sources (verify the licence of each at Stage 0) | Used for |
| --- | --- | --- |
| Legal contracts | SEC EDGAR material-contract exhibits (public filings); the CUAD dataset of 510 commercial contracts with expert clause annotations (published under a Creative Commons licence) | Ingestion, structure detection gold, retrieval evaluation |
| Legal authority | US court opinions from CourtListener and the Caselaw Access Project (public domain); US Code, CFR and Federal Register from govinfo.gov (public domain); HIPAA rules (45 CFR Parts 160 and 164) | Citation and clause-level retrieval; regulatory filings |
| Legal evaluation | Published retrieval and entailment benchmarks built on real contracts (for example LegalBench-RAG and ContractNLI) | Retrieval floors, entailment calibration |
| Medical narratives | PubMed Central open-access case reports with permissive licences (JATS XML plus PDF) | Structure detection, retrieval, validator calibration |
| Medical structured | DailyMed drug labels (SPL XML); FDA guidance; CDC and WHO guidelines where the licence allows; ClinicalTrials.gov records | Structured chunking, dose and unit matching |
| Medical evaluation | Published biomedical question-answering sets with snippet ground truth (for example BioASQ, after registration), claim-verification sets where licences allow | Retrieval floors, entailment calibration |
| Scanned and OCR | Real public-domain scanned archive PDFs, plus real born-digital pages rasterized with scanner-like transformations so ground-truth text is known exactly | OCR and quarantine gates |
| Credentialed lane (opt-in) | MIMIC-IV-Note or similar under a data use agreement and a self-hosted model only | SOAP-style structure checks; never in shared CI |
| Human labels | A held-out set of at least 300 sentence–chunk pairs per domain labeled by a qualified attorney or clinician | Final authority for validator calibration |

Minimums (G0.8): 150 legal and 150 medical documents; at least 30 scanned multi-page PDFs; at least 10 documents of 100 to 200+ pages; at least 5 JATS, 20 SPL and 20 DOCX items. Non-commercial sets are used only if marked `internal_eval_only` and never shipped. The corpus is refreshed quarterly; a refresh is a manifest change reviewed like code.

## Appendix C — Configuration catalog (names only) and policy minimums

Real secrets never appear in the repository. `.env.example` documents every variable; groups below use prefixes.

| Group | Names (prefix) | Notes |
| --- | --- | --- |
| Auth0 | `AUTH0_DOMAIN`, `AUTH0_AUDIENCE_MAIN`, `AUTH0_AUDIENCE_ONBOARDING`, `AUTH0_CLIENT_ID_BFF`, `AUTH0_CLIENT_SECRET_BFF`, `AUTH0_M2M_CLIENT_ID`, `AUTH0_M2M_CLIENT_SECRET`, `AUTH0_CLAIMS_NAMESPACE` | M2M variables exist only in the identity service's environment |
| Database | `PG_DSN_<SERVICE>` (one per service), `PGBOUNCER_*` | One role per service |
| Vector | `QDRANT_URL`, `QDRANT_KEY_RO` (retrieval), `QDRANT_KEY_RW` (ingestion) | |
| Cache | `VALKEY_URL`, `VALKEY_USER_<SERVICE>` | |
| Object store | `OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_CREDS_INGESTION` | |
| Keys | `KMS_PROVIDER`, `KMS_ORG_KEY_ALIAS_PREFIX`, `KMS_TRUST_ROOT_ID`, `KEYGUARD_*`, `CODE_PEPPER_ID` | Pepper material lives in the secret manager |
| Models | `LLM_PROVIDER`, `LLM_API_KEY_<ORG>`, `LLM_TEST_BUDGET_USD`, `EMBEDDING_MODEL`, `RERANK_MODEL`, `NLI_MODEL_HASH` | |
| Mail | `SMTP_*`, `IMAP_*` | Real mailbox on a project-owned domain |
| Observability | `OTEL_*` | |

Policy minimums that the production profile must meet (checked by a lint test; test profiles may use short values):

| Setting | Production requirement |
| --- | --- |
| Successor transfer, wall lift, private-read enable waits | at least 72 h, 24 h, 24 h |
| Workspace unseal wait; workspace destroy wait | at least 72 h; at least 30 days |
| Organization deletion grace; KMS deletion window (non-drill keys) | at least 30 days; exactly 30 days |
| Governance approval expiry | at most 72 h |
| Owner recovery wait | at least 72 h |
| Step-up maximum age; access-token lifetime; context-token lifetime; signer-certificate lifetime | at most 300 s; 600 s; 60 s; 3,600 s |
| Privileged idle timeout; privileged absolute session | at most 15 min; 8 h |
| Emergency access duration; per-user daily limit | at most 60 min; at most 5 |
| Break-glass session duration | at most 60 min |
| Operator infrastructure, control-plane and content session maximums | at most 24 h, 8 h, 4 h |
| Backup retention | at most 35 days |
| MFA policy; SMS and email OTP factors | always on; disabled |

