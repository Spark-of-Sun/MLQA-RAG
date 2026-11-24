# Requirements Document

## Introduction

This document states the requirements for the full Legal/Medical Document Q&A system described in the master design
`/home/gk/Downloads/LMQA/project-blueprint/Legal-Medical-QA-Master-System-Design-v3.1.md` (version 3.1, October 25,
2026, referred to below as "the design" and cited as §n). The system answers natural-language questions over legal and
medical documents, releases only sentences that a deterministic validator has verified against page- and clause-level
citations, refuses when the documents do not support an answer, and isolates organizations, workspaces, matters and
private documents with PostgreSQL row-level security as the final authority.

An MVP already exists in this repository (product name "Cyte"). Every requirement below carries a status measured
against that code. The requirements follow the design's architecture (Auth0 authenticates, PostgreSQL authorizes; a
Gateway in front of separate services; Qdrant behind a filtering wrapper; per-organization KMS keys behind a provider
interface with AWS KMS as the design's reference adapter and OpenBao locally). They do not default to AWS-native
services beyond what the design names.

Kubernetes is out of scope for this spec at the user's request and will be added later. Kubernetes-related design
content is marked "Deferred by user" in the coverage table.

### Structure of this document

This document follows the PRD guide (`.kiro/steering/prd-guide.md`) mapped onto Kiro's requirements format:

- Overview, personas, priorities, technology landscape and constraints come first.
- Each requirement has an ID (`R-n`), a type (FR functional, NFR non-functional, DR data, IR integration, MLR ML),
 a priority, a persona, the design sections it comes from, the gate checks that prove it (`G#.#`, §20), a user
 story, EARS acceptance criteria, a status and evidence.
- After the requirements: the MVP-versus-design deviation register, open questions, out-of-scope items, success
 metrics and the heading coverage table.

### Status legend

| Status | Meaning |
| --- | --- |
| Implemented | Code was found in this repository that addresses every acceptance criterion of the requirement. This does not mean the gate passed. The "Verification" note says whether tests ran. |
| Partial | Code was found for some acceptance criteria. The evidence names which criteria are met and which are not. |
| Not started | No code was found for any acceptance criterion. |

Two facts from the repository qualify almost every status:

1. `docs/production.md` states that the production code for Stages 1 to 9 is "written, not yet tested", that
 migrations `0006` to `0008` have not been applied to any database, and that only the Stage 0 suites ran.
2. Most production paths sit behind flags in `contracts/features.toml`, and every flag is `enabled = false`. A disabled
 feature's routes answer 404 (`services/gateway/src/gateway/app.py`, `guard`). Code behind a disabled flag is
 reported as found, with the note "flag off".

`STAGE` contains `0`, so under the design's gatekeeper no stage beyond Stage 0 is proven (§19.6).

## Overview

Product summary (from §1.1): questions over large legal and medical document sets (contracts, case files, clinical
documents, regulatory filings) answered with machine-verified, page- and clause-level citations; refusal when the
documents do not support an answer; multi-tenant for law firms and hospital systems; audit-logged end to end; no
unsupported answer shown to a user.

The design delivers the system in twelve gated stages (§1.4, §20). Each stage must pass its gate before the next
begins, and gates are cumulative.

### Challenge check (PRD guide)

These are observations from comparing the design with the MVP. They add no requirements.

1. Funding objection: the design puts twelve gated stages before go-live, and the MVP already demonstrates the product. A budget holder will ask what the gates buy. The design's answer is that every guarantee is a claim until its gate passes (§1.5); today only Stage 0 has run.
2. Most likely total failure: a cross-scope leak or an unverified answer reaching a legal or clinical user. The MVP's largest exposures against the design are BYPASSRLS on the control-plane and ingestion paths (DEV-13), plaintext content at rest (DEV-09), a generative LLM inside validation (DEV-05) and embeddings shared across workspaces (DEV-04).
3. Simpler version: the design itself allows a reduced `mvp` gate profile that may cut sizes and features but never a safety threshold (§19.6). The companion document that defines that profile was not provided (Q-14).
4. Acknowledged but unmitigated risk: third-party processors. The MVP sends document text to Gemini for embeddings and to a configurable answer provider, with a global cross-provider fallback chain (DEV-03, DEV-31). The design requires per-organization providers under BAA or no-retention terms before real data (§11.8).
5. Persona drift: the MVP added features for tenants (chats, profiles, named shares, a public website) that the design does not specify (DEV-21), while Super Admin governance, co-owner and operator flows remain behind disabled flags (DEV-19).

## Personas

| Persona | Description (design source) | Primary workflows | Requirements |
| --- | --- | --- | --- |
| Super Admin (and co-owner) | Created the organization; governs admins; never reads content (§3.2, §5.3) | Create organization, Organization Code, approve admins, governance requests, organization deletion | R-1, R-3, R-9, R-12, R-13, R-15, R-16, R-18, R-55, R-56, R-72, R-73 |
| Admin | Runs one workspace; manages tenants; does document work (§3.2) | Admin Code, approve tenants, matters, grants, walls, break-glass, uploads, questions | R-4 to R-8, R-14, R-17, R-74, R-75, R-81 |
| Tenant | End user inside one workspace: attorney, paralegal, clinician, reviewer (§3.2) | Join with Admin Code, upload, ask, read cited answers, emergency access | R-4, R-7, R-14, R-44 to R-48, R-75 |
| Platform operator | Our staff with no standing access (§14) | JIT access requests, KeyGuard approvals, owner recovery, security holds | R-66 to R-69, R-76 |
| Engineer and gatekeeper | Builds the stages and runs the gates (§18 to §20) | Toolchain, tests, gates, stage advancement | R-83 to R-99 |
| External reviewer (counsel, security architect, penetration tester) | Required external step (§25) | Compliance mapping, review package, sign-off | R-65, R-97 |

## Priority definitions

The design gives no P0/P1/P2 labels. Priorities below are derived from the design's stage order, not invented:

| Priority | Meaning | Design stages |
| --- | --- | --- |
| P0 | Core safety path: toolchain, data isolation, keys, identity, gateway trust, ingestion, retrieval, generation, validation and gated delivery | Stages 0 to 7 |
| P1 | Required before go-live: frontend, governance, audit service, operators, lifecycle and destruction | Stages 8 and 9 |
| P2 | System verification at scale and production readiness | Stages 10 and 11 |

## Technology landscape

The PRD guide asks for a current-year web check of every technology choice with a source link. That check was not run
in this pass. The design's own ledger (§4.5) records vendor facts checked on October 23, 2026, and the repository's
`docs/versions.md` (generated by `tools/gen_versions.py`) records the resolved versions. Every row below is therefore
marked "unverified on the web in this pass; requires validation at pin", and the lockfile stays the authority (§4.5).

| Layer | Design choice (§4.5) | Resolved in the MVP (`docs/versions.md`, `pyproject.toml`, `frontend/package.json`, `compose.yaml`) |
| --- | --- | --- |
| Python and tooling | Python 3.14, `uv`, `ruff` 0.16.x, `pytest` 9.1.x, `pyright` blocking | Python 3.14.4, uv 0.13.9, ruff 0.17.6, pytest ≥ 9.2, pyright 1.1.414 (skipped by the `mvp` gate profile) |
| Web framework | FastAPI, Pydantic 2.13+ | FastAPI and Pydantic v2 (`services/gateway/src/gateway/app.py`) |
| Relational database | PostgreSQL 18 through PgBouncer | `pgvector/pgvector:pg18` (PostgreSQL 18.7, pgvector 0.8.7); PgBouncer container present |
| Vector database | Qdrant 1.19.x | Qdrant 1.20.0 container present; request path uses pgvector (deviation DEV-02) |
| Cache and pub/sub | Valkey 9.1.x | Valkey 9.2.0 |
| Jobs | Procrastinate, Celery 5.6 fallback | Procrastinate ≥ 3.12 (dev dependency; production worker in `services/ingestion/src/ingestion/production.py`) |
| Object storage | S3 in production, SeaweedFS locally | SeaweedFS container; MVP writes originals to `data/objects` (deviation DEV-22) |
| Frontend | Next.js 16.3.x, React 19.2, Node 24, `@auth0/nextjs-auth0` v4, Tailwind 4, shadcn/ui | Next.js 16.4.6, React 19.3.1, Node 24.21.0, `@auth0/nextjs-auth0` 4.33.0, Tailwind 4.3.5, no shadcn/ui |
| Identity | Auth0 Universal Login, Organizations, Actions, passkeys, M2M | Auth0 Universal Login; Organizations behind a disabled flag |
| Infrastructure as code | OpenTofu with Auth0 and AWS providers | `infra/auth0/main.tf`, `infra/aws/main.tf` |
| Keys | AWS KMS (reference), OpenBao Transit locally | `lmqa_keys` adapters for both; OpenBao 2.7.2 container |
| Embeddings | `bge-m3` or Qwen3-Embedding, self-hosted | Gemini embeddings, 768 dimensions (deviation DEV-03) |
| Re-ranker | `bge-reranker-v2-m3` or Qwen3-Reranker | `BAAI/bge-reranker-v2-m3` ONNX, local |
| Entailment | DeBERTa-v3 NLI cross-encoder, pinned | ONNX NLI code behind a disabled flag; MVP uses an LLM pass (deviation DEV-05) |
| Parsing and OCR | Docling, Tesseract 5, `pypdfium2`; bake-off | Text layer, DOCX, HTML, XML parsers; Tesseract and `pypdfium2` OCR code behind a disabled flag |
| Malware scan | ClamAV | ClamAV container in profile `scan`; code behind a disabled flag |
| Observability | OpenTelemetry, Grafana (Loki, Tempo, Prometheus) | `grafana/otel-lgtm:latest` in profile `observability`, not pinned by digest; no instrumentation found |
| Load and browser tests | k6, Playwright | Not found |
| Supply chain | CycloneDX SBOM, cosign, attestations, Trivy, gitleaks, Semgrep | gitleaks only (`.githooks/pre-commit`, `.github/workflows/secret-scan.yml`) |

## Constraints

These come from the design and bind every requirement:

- C1. Real data from the first stage: no synthetic documents, mocked stores or mock identity provider (§2.3, §19.1).
- C2. Auth0 handles sign-up and login through Universal Login (§2.3, §7.1).
- C3. `pytest` and `ruff` are blocking gates in every stage (§2.3).
- C4. Local-host first: everything except Auth0, KMS, the audit anchor bucket, the LLM provider and a test mailbox
 runs on one machine through Docker Compose (§2.3).
- C5. Customer data never enters local, CI or staging environments (§2.4 A4).
- C6. Documents are English in v1 (§2.4 A6).
- C7. One user holds one membership in v1; the schema allows more later (§2.4 A2, D7).
- C8. AWS is the reference cloud for KMS and S3; other clouds are reached through adapter interfaces (§2.4 A3, D23).
 Kubernetes (EKS in A3) is deferred by the user.
- C9. Counsel reviews privilege, retention, ethical-wall and HIPAA interpretations before any customer data is
 processed (§2.4 A5).
- C10. Trust assumptions of §25.2 hold: stores unreachable from the public internet, CI cannot be bypassed, Auth0
 enforces MFA and membership as configured, clocks are synchronized, KMS and Object Lock behave as documented.

## Glossary

- **Platform**: The whole Legal/Medical Q&A system described by the design.
- **Organization**: Top-level customer boundary created by one Super Admin; owns one KMS key, one data partition and
 one Auth0 Organization (§3.2).
- **Workspace**: Isolation unit created for each admin; holds documents, matters, memberships, walls and audit (§3.2).
- **Super_Admin**: Account that created the organization; a co-owner is a second Super Admin membership (§3.2).
- **Admin**: Runs one workspace, manages its tenants and does document work (§3.2).
- **Tenant**: End user inside exactly one workspace (§3.2). The MVP user interface calls this role "member".
- **Matter**: Matter or patient sub-scope inside a workspace (§3.2).
- **Wall**: Explicit deny for one user on one matter that beats every grant, ownership and admin role (§3.2, §5.6).
- **Grant**: A tenant's access to one matter with a `max_tier` ceiling and an optional expiry (§5.4).
- **Confidentiality_Tier**: 1 internal, 2 confidential, 3 privileged_or_phi, 4 restricted (§5.5).
- **Organization_Code**: 64-character secret to request admin membership in one organization (§7.6).
- **Admin_Code**: 32-character secret to request tenant membership in one workspace (§7.6).
- **Principal**: Verified identity of a request: user, organization, workspace, role, status, authentication strength,
 scope hash (§3.2).
- **Scope_Hash**: Digest of what a principal can see, maintained by database triggers, keying caches and ledgers.
- **Context_Token**: Short-lived ES256 JWT minted by the Gateway for one internal service (§9.1).
- **Signer_Certificate**: Hour-long certificate, signed by the KMS trust root, binding a Gateway or Validator
 instance's ephemeral public key (§9.1).
- **Governance_Request**: Two-person, time-windowed control-plane action (§6.7).
- **Access_Session**: Break-glass, clinical emergency or operator JIT session with a hard expiry (§6.8).
- **Retrieval_Ledger**: The `retrieval_records` rows written by retrieval and read by generation and the Validator
 (§9.4).
- **Alias**: Request-local chunk name the model sees instead of a global chunk ID (§9.4, §11.5).
- **Verdict**: The Validator's signed decision on one sentence (§11.6).
- **Gate**: A set of mechanical checks that must all pass before the next stage (§3.2, §19.6).
- **Gateway**: Service on port 8000: token verification, principal resolution, route allow-list, rate limits,
 idempotency, context-token minting and release of verified sentences (§4.2).
- **Identity_Service**: Service on port 8005: onboarding, organizations, workspaces, memberships, codes, governance,
 Auth0 sync, provisioning saga and revocation fan-out (§4.2).
- **Ingestion_Service**: Service on port 8001 with its worker, indexer and reconciler (§4.2).
- **Retrieval_Service**: Service on port 8002: scope resolution, hybrid search, PostgreSQL cross-check, re-ranking,
 ledger write (§4.2).
- **Generation_Service**: Service on port 8003: token budget, compression, prompt assembly, LLM call, scoped cache
 (§4.2).
- **Validator**: The `citation_validator` service on port 8004: segmentation, checks V1 to V8, signed verdicts (§4.2).
- **Audit_Service**: Service on port 8007: audit read, search, export, chain verification, anchoring (§4.2).
- **Ops_Service**: Operator-plane API on port 8006 behind a separate ingress and identity provider (§4.2, §14).
- **Frontend**: The Next.js 16 application and its BFF route handlers on port 3000 (§4.2, §17).
- **Database**: PostgreSQL 18 with FORCE row-level security, the final access authority (§10.3).
- **Vector_Library**: `lmqa_vectorstore`, the only holder of a Qdrant client (§4.7, §10.5).
- **Object_Store_Library**: `lmqa_objectstore`, the S3-compatible adapter with application-level encryption (§12.3).
- **Key_Ring**: The key hierarchy in use in `lmqa_keys`: organization CMK, workspace content keys, document keys,
 audit keys, cache keys (§12.1).
- **KeyGuard**: The only workflow allowed to disable or destroy organization keys (§12.5).
- **Indexer**: Worker that applies `index_outbox` rows to the vector store (§10.6).
- **Reconciler**: Job that compares vector payloads with PostgreSQL and repairs drift (§10.6).
- **Identity_Worker**: Worker that runs saga steps, Auth0 sync and revocation fan-out (§4.2).
- **Gatekeeper**: `tools/gatekeeper`, the required status check that enforces stage ownership and attestations
 (§19.6).
- **Toolchain**: The CI gate steps: `uv`, `ruff`, `pyright`, frontend checks, import-linter, contract lint, gitleaks,
 dependency audit and `pytest` (§19.6).
- **Doctor**: `make doctor`, which verifies every real dependency before tests run (§4.6).
- **Test_Suite**: The `pytest` suites with stage and kind markers (§19.2).
- **Eval_Harness**: The evaluation harness under `eval/` with floors in `eval/floors.toml` (§11.3, §11.7).
- **Corpus_Loader**: `tools/load_corpus`, which loads the public corpus through the real onboarding and upload APIs
 (§3.3, §18).
- **Auth0_Config**: The OpenTofu configuration of the Auth0 tenants in `infra/auth0/` (§8.2).
- **Step_Up**: A fresh authentication within 5 minutes at the strength the role requires (§8.7, §15.1).
- **Feature_Flag**: An entry in `contracts/features.toml` bound to gates; a disabled feature's endpoints answer 404
 (§18, §19.6).
- **MVP**: The code in `/home/gk/Downloads/LMQA/legal-medical-qa` at the time of this document.

## Requirements

### Requirement 1: Tenancy hierarchy and containment

**ID:** R-1 · **Type:** DR · **Priority:** P0 · **Persona:** All · **Design:** §1.2, §2.4 A1 and A2, §3.1 principles 1 and 2, §5.1, D7 · **Gates:** G1.5, G1.6

**User Story:** As a customer organization, I want every row, vector, object, cache entry and audit event tied to my organization and workspace, so that no data can point into or leak across another scope.

#### Acceptance Criteria

1. THE Database SHALL store a non-null `org_id` on every row of every table whose rows belong to an Organization and on every audit event, and SHALL also store a non-null `workspace_id` on every row and audit event that belongs to a Workspace (including Admin and Tenant memberships, Admin_Code join codes, matters, documents, chunks, walls and workspace-scope audit events); rows that belong to an Organization but to no Workspace, such as Super_Admin memberships and organization-scope audit events, carry `org_id` only.
2. THE Platform SHALL include the `org_id` and the owning Workspace's `workspace_id` in every vector payload written through the Vector_Library, every object key written through the Object_Store_Library and every cache key that holds Workspace data, and SHALL include the `org_id` in every cache key that holds Organization data.
3. THE Database SHALL declare every foreign key between two tables that carry `workspace_id` under criterion 1 as a composite key that includes `org_id` and `workspace_id`.
4. IF an INSERT or UPDATE would make a row reference, through any foreign key, a row whose `workspace_id` or `org_id` differs from its own, THEN THE Database SHALL reject the statement with a foreign-key violation and leave both rows unchanged.
5. THE Database SHALL record exactly one Organization for every Workspace, exactly one owning Admin membership for every Workspace, and exactly one Workspace for every Admin and Tenant membership.
6. THE Database SHALL store each membership as its own row of the `memberships` table, with no constraint that limits a user to one row in total, so that several memberships per user can be enabled after v1 (D7).
7. IF an INSERT or UPDATE would give a user a second live membership, where a live membership is one in state `pending_approval`, `active` or `suspended`, THEN THE Database SHALL reject the statement and leave the user's existing membership unchanged.
8. THE Platform SHALL provide no route or service operation that changes the role (`super_admin`, `admin` or `tenant`) of an existing membership, so that a person who needs a different role is off-boarded (membership moved to `removed`) and re-onboarded through a new membership.
9. THE Platform SHALL hold, for each Organization, exactly one live primary Super_Admin membership and at most one live co-owner membership, and both memberships SHALL have the `super_admin` role.
10. THE Platform SHALL take `org_id`, `workspace_id`, role and scope for every request only from the `sub` and `org_id` claims of the verified token and from the Database, so that values of these fields supplied in a request body, query string or client header do not change the Organization, Workspace, role or scope the request runs under.

**Status:** Partial

**Evidence:** Criteria 3, 4 and 6 are met in `db/migrations/0001_schema.sql` (composite foreign keys `(org_id, workspace_id)` on memberships, join_codes, documents, chunks and queries). Criteria 5 and 7 are partly met: the unique indexes `memberships_one_live_per_user` and `memberships_one_admin_per_workspace` (`db/migrations/0001_schema.sql`, lines 46–48) use the predicate `status <> 'rejected'`, so they also count removed and suspended memberships; this blocks re-onboarding after removal and the §7.8 successor join. Criterion 8 is met in the MVP API: no role-change route exists in `contracts/authz-matrix.yaml`. Criterion 10 is met for the MVP routes: `services/gateway/src/gateway/app.py` takes role and workspace from `IdentityService.resolve`, and no route accepts `org_id` or `workspace_id`. Criteria 1 and 2 are partly met: object keys `org_{id}/ws_{id}/doc_{id}/v{n}` (`libs/lmqa_objectstore/src/lmqa_objectstore/__init__.py`) and Valkey key prefixes exist, but `embedding_cache` is keyed by organization only (DEV-04). Criterion 9: a `co_owner` column exists (`db/migrations/0006_production_core.sql`), but no co-owner flow is reachable (R-15). The token `org_id` is not used (R-22).

### Requirement 2: Role permission matrix and route allow-list

**ID:** R-2 · **Type:** FR · **Priority:** P0 · **Persona:** All · **Design:** §5.2, §5.3 level 1, §15.1, §17.1 · **Gates:** G3.6, G8.1

**User Story:** As a security reviewer, I want one machine-readable role-by-route matrix that drives the Gateway, the frontend client and the authorization tests, so that the three cannot drift apart.

#### Acceptance Criteria

1. THE Gateway SHALL build its route allow-list from `contracts/authz-matrix.yaml`, which lists for each route (method and path) the roles allowed to call it and whether the route requires step-up.
2. IF an authenticated caller's role is not listed for the requested route in `contracts/authz-matrix.yaml`, THEN THE Gateway SHALL answer 404 with the same response it gives for a route that does not exist.
3. IF the routes in code, the OpenAPI documents under `contracts/openapi/` and `contracts/authz-matrix.yaml` disagree on any route or role, THEN THE Gateway SHALL refuse to start.
4. IF the routes in code, the OpenAPI documents under `contracts/openapi/` and `contracts/authz-matrix.yaml` disagree on any route or role, THEN THE Toolchain SHALL fail the build.
5. WHEN a caller whose role is listed calls a route marked step-up in `contracts/authz-matrix.yaml` and the caller's last authentication is older than 5 minutes or weaker than the strength the role requires, THE Gateway SHALL return a step-up challenge and SHALL NOT execute the request.
6. THE Platform SHALL grant each role (Super Admin, Admin, Tenant) exactly the capabilities in the §5.2 permission matrix, with no capability beyond it.
7. IF a request names a resource ID outside the caller's scope, THEN THE Gateway SHALL answer 404 with the same response it gives for a resource that does not exist.
8. IF a system-level refusal occurs (for example no vector filter can be built for the principal), THEN THE Gateway SHALL answer 403.
9. THE Frontend SHALL apply the §17.1 route table: forbidden routes answer 404, a Super Admin requesting `/chat` or `/library` is redirected to Manage Admins, and pending or suspended users are blocked from every route except the `/onboarding` status page.

**Status:** Partial

**Evidence:** Criteria 1, 2, 3 and 4 (code part) are met: `services/gateway/src/gateway/app.py` (`guard`, `_check_matrix_drift`) and `contracts/authz-matrix.yaml`; `tests/contract/test_stage0_toolchain.py::test_openapi_and_authz_matrix_agree`. Criterion 5 has code: `guard` raises `StepUpRequired` for routes whose matrix rule sets `step_up` (`services/gateway/src/gateway/app.py`, lines 175–178), but it requires `passkey` for every role instead of a per-role strength. Criterion 6 is partly met: the MVP matrix covers onboarding, admin and tenant management, documents, queries and audit, but most §5.2 capabilities (matters, walls, emergency access, break-glass, governance, operator approvals) are flag-gated or absent, and the matrix carries MVP-only routes (DEV-26). Criterion 7: out-of-scope document IDs return 404 through RLS. Criterion 8: no 403 path for "no filter can be built" exists in the MVP pgvector path. Criterion 9 was not verified in this pass; R-3 cites `frontend/src/app/(super-admin)/layout.tsx` and redirects or 404s on the chat and library routes.

### Requirement 3: Super Admin boundary

**ID:** R-3 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin · **Design:** §5.3, §16.3, DEF-41 · **Gates:** G1.5, G3.6

**User Story:** As a tenant, I want the organization owner to be unable to read my documents or questions, so that governing accounts never implies reading content.

#### Acceptance Criteria

1. WHEN a `super_admin` principal sends a request to `/v1/query`, `/v1/documents` or any workspace endpoint, THE Gateway SHALL answer 404.
2. THE Platform SHALL contain no service code path that resolves tenant resources for the `super_admin` role.
3. THE Database SHALL define `super_admin` policies only on `orgs`, `join_codes`, `workspaces` (metadata), `memberships` rows whose member is an admin, the Super Admin's own and co-owner membership rows, `governance_requests`, `workspace_usage` and organization-scope audit events.
4. WHEN a `super_admin` principal queries documents, chunks, tenant memberships, walls or audit payloads, THE Database SHALL return zero rows, whichever code path issues the query.
5. WHEN a Super Admin requests a successor transfer, THE Platform SHALL create a Governance_Request, send a notice to every tenant of the affected workspace and to the outgoing admin, and write an audit event that no `super_admin` route or policy can delete or alter.
6. IF the approver of a successor transfer is the initiating Super Admin, the approval has no passkey Step_Up, or fewer than 72 hours have passed since the request, THEN THE Platform SHALL refuse to apply the transfer and leave the workspace's admin unchanged.
7. WHEN a successor transfer takes effect, THE Platform SHALL set the workspace's `admin_can_read_private` to false.

**Status:** Partial

**Evidence:** Criterion 1 is met: `contracts/authz-matrix.yaml` lists no data-plane route for `super_admin`; `frontend/src/app/(super-admin)/layout.tsx` and the chat and library routes redirect or 404. Criterion 2 has not been verified. Criterion 4 is met for content tables in the MVP because `app_active_workspace()` returns NULL for `super_admin` (`db/policies/10_helpers.sql`). Criterion 3 is not met: identity calls for every role run on `lmqa_system`, which has BYPASSRLS (`libs/lmqa_db/src/lmqa_db/database.py`, `db/roles/grants.sql`), so the boundary for control-plane reads is enforced in code, not by a `super_admin` policy set (DEV-13). Criteria 5 to 7: `successor_transfer_effect` exists in `services/identity/src/identity/lifecycle.py` behind the disabled `governance_requests` flag (R-18).

### Requirement 4: Single access decision

**ID:** R-4 · **Type:** FR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §5.4, §10.3, DEF-02, DEF-59, D2 · **Gates:** G1.4, G5.4, G5.6

**User Story:** As a workspace member, I want one access decision applied identically by the database, the vector filter and the test oracle, so that what I can retrieve is exactly what I am allowed to read.

#### Acceptance Criteria

1. THE Database SHALL evaluate document and chunk access using only these rules, in this order, with the first matching rule deciding: (1) the user's membership, the workspace or the organization is not in state `active` → deny; (2) a wall exists for the user on the document's matter → deny; (3) the user owns the document → allow; (4) the role is admin and visibility is `matter` → allow at all tiers; (5) the role is tenant, visibility is `matter`, the user holds an unexpired grant on the matter, and the grant's `max_tier` is at or above the document's tier → allow; (6) the role is tenant in a workspace of deployment type `medical` or `both`, visibility is `matter`, the user holds an active emergency exception on the matter, and the document's tier is at or below the emergency tier cap → allow read and query only, no export; (7) the role is admin, visibility is `private`, `admin_can_read_private` is true, and the admin holds an active break-glass session → allow read and query only; (8) anything else → deny.
2. IF an insert or update would leave a document with visibility `matter` and no `matter_id`, THEN THE Database SHALL reject the statement through a CHECK constraint and leave the row unchanged.
3. THE Database SHALL default `admin_can_read_private` to false.
4. THE Vector_Library SHALL build, from a principal, a filter whose result set equals or is a superset of the rows RLS returns for that same principal.
5. THE Test_Suite SHALL include a pure-Python oracle of the rules in criterion 1 and SHALL assert, over at least 20,000 generated scenarios, that RLS returns exactly the oracle's answer for every role, table and operation.
6. THE Database SHALL define no policy on documents or chunks for the `super_admin` role or any operator role, and SHALL return zero document and chunk rows to those principals.

**Status:** Partial

**Evidence:** Criteria 2 and 3 are met in code: `db/migrations/0006_production_core.sql` (`documents_matter_visibility`, `admin_can_read_private default false`); migrations 0006 to 0008 were never applied (`docs/production.md`). Criterion 1 is partly met: rules (1) to (8) are coded in `db/policies/11_access.sql` (`app_can_read`, helpers `app_walled`, `app_grant_tier`, `app_emergency_cap`, `app_break_glass_active`), but `app_can_read` also applies MVP rules 7a (visibility `workspace`) and 7b (`document_shares`), which are not in the design, so access is not decided by these rules only (DEV-14). Criterion 4: `libs/lmqa_vectorstore/src/lmqa_vectorstore/qdrant.py` (`build_filter`) mirrors the rules, flag `qdrant_vectors` off. Criterion 5: the oracle exists in `libs/lmqa_testing/src/lmqa_testing/oracle.py`; no test compares it with RLS. Criterion 6 holds for `super_admin` (R-3); the `ops_metadata_ro` role is created conditionally in `db/policies/15_force_rls.sql`.

### Requirement 5: Confidentiality tiers

**ID:** R-5 · **Type:** DR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §5.5, DEF-17 · **Gates:** G5.6, G5.7

**User Story:** As an admin of a medical or legal workspace, I want each document and chunk to carry a confidentiality tier that grants cap, so that minimum-necessary access has a source of truth.

#### Acceptance Criteria

1. THE Database SHALL store on every document and every chunk a `confidentiality_tier` from 1 to 4 (1 `internal`, 2 `confidential`, 3 `privileged_or_phi`, 4 `restricted`).
2. THE Database SHALL store on every grant a `max_tier` from 1 to 4 that states the highest tier the tenant may read on the grant's matter.
3. IF an upload requests a `confidentiality_tier` above the uploader's own tier ceiling on the target matter, THEN THE Database SHALL reject the insert and leave no document row, where an admin's ceiling is tier 4 (§5.4 rule 4) and the ceiling for a private document with no matter is tier 4 (assumed default; not stated in design, see Q-28).
4. THE Database SHALL deny every tier-4 document and chunk to a principal whose only access basis is an emergency exception.

**Status:** Partial

**Evidence:** All four criteria have code: `tier smallint check (tier between 1 and 4)` on documents and chunks and `matter_grants.max_tier` in `db/migrations/0006_production_core.sql`; the upload ceiling in the `documents_insert` policy in `db/policies/20_rls.sql`; `least(cap, 3)` in rule 6 of `app_can_read` (`db/policies/11_access.sql`). Status is Partial because the MVP upload API (`services/ingestion/src/ingestion/documents.py`, `upload`) accepts no tier or matter, the matter routes are behind the disabled `matters_walls_tiers` flag, and the migration was never applied.

### Requirement 6: Ethical walls

**ID:** R-6 · **Type:** FR · **Priority:** P0 · **Persona:** Admin · **Design:** §5.6, §6.7 `wall_lift`, DEF-55, D26 · **Gates:** G5.5

**User Story:** As a law-firm admin, I want to screen a user from a matter instantly and make lifting the screen a two-person decision, so that conflicts are handled the way legal practice requires.

#### Acceptance Criteria

1. WHEN an admin creates a wall for a user on a matter, THE Identity_Service SHALL make the wall effective from that user's next request, with no second approver.
2. THE Database SHALL deny a walled user every document and chunk of the walled matter, including documents the user owns and access through a grant, the admin role or an emergency exception.
3. THE Vector_Library SHALL add a `must_not` condition on each walled matter to the filter built for a walled user.
4. THE Platform SHALL include each of a user's walls in the scope hash that keys that user's caches.
5. THE Platform SHALL show a walled user no document of the walled matter in the citation side panel.
6. WHEN a wall is created, THE Gateway SHALL close the walled user's open streams within the revocation SLO of R-23.
7. WHEN an admin requests to lift a wall on a tenant, THE Identity_Service SHALL create a `wall_lift` governance request with the Super Admin as second approver and a 24-hour wait, and SHALL notify the affected user when the request executes.
8. WHEN a lift of a wall on an admin is requested, THE Identity_Service SHALL accept the `wall_lift` request only from the Super Admin and SHALL require an operator `security_officer`, after out-of-band confirmation, as the second approver.
9. THE Database SHALL return wall rows only to the admin of the wall's workspace and, as opaque rows (IDs and reason code only), to the second approver of an open `wall_lift` request, so that the walled user sees only "no access".
10. WHEN a wall is created, THE Platform SHALL leave document rows and vector payloads unchanged.

**Status:** Partial

**Evidence:** Code exists for criteria 1, 2, 3, 4, 7, 8 and 10: `services/identity/src/identity/scope_admin.py` (`create_wall`, `wall_on_admin`, `lift_wall_effect`), `db/policies/11_access.sql` (`app_walled`, trigger `scope_walls`), `libs/lmqa_vectorstore/src/lmqa_vectorstore/qdrant.py` (`build_filter`), `services/identity/src/identity/governance.py` (`list_for_org` opaque IDs). All of it is behind the disabled `matters_walls_tiers` and `governance_requests` flags and untested. Criterion 6: no code links wall creation to stream cutting was found (the scope trigger sends `pg_notify('lmqa_scope')`, but the revocation consumer in `services/gateway/src/gateway/trust.py` handles principal revocations). Criteria 5 and 9 were not verified in code.

### Requirement 7: Clinical emergency access

**ID:** R-7 · **Type:** FR · **Priority:** P0 · **Persona:** Tenant (clinician) · **Design:** §5.7, D25 · **Gates:** G5.7, G9.8

**User Story:** As a clinician without a grant to a patient, I want a time-boxed, loud emergency override, so that I can treat a patient while every use is reviewed.

#### Acceptance Criteria

1. WHERE the workspace's deployment type is `medical` or `both` and the admin enabled `emergency_access` (default off), THE Identity_Service SHALL let any active tenant without a grant to a patient or matter request emergency access to that patient or matter.
2. WHEN a tenant requests emergency access with a reason code from the fixed list and a free-text note, THE Identity_Service SHALL create an `access_exceptions` row of kind `emergency` that expires 60 minutes after creation, permits read and query only, forbids export and caps the tier at 3.
3. IF a tenant who already holds the per-user daily limit of emergency exceptions (configurable, at most 5 in production, Appendix C) created within the preceding rolling 24 hours (assumed default; not stated in design, see Q-29) requests another, THEN THE Identity_Service SHALL refuse the request and create no exception.
4. WHEN an emergency exception is created, THE Identity_Service SHALL notify the workspace admin.
5. WHILE an emergency exception is active, THE Audit_Service SHALL flag every query the tenant makes under that exception at break-glass severity.
6. WHEN an emergency exception is created, THE Identity_Service SHALL create a post-hoc review task for the admin, due 72 hours after creation.
7. IF a review task is still open 48 hours or 72 hours after creation, THEN THE Platform SHALL raise an alert at each of those two points.
8. WHEN the admin ends an emergency exception, THE Identity_Service SHALL set the exception to `revoked`, bump the scope version and publish the invalidation message.
9. THE Database SHALL deny documents in walled matters and tier-4 documents to a tenant whose access basis is an emergency exception.

**Status:** Partial

**Evidence:** Code for criteria 1, 2, 3, 6, 7, 8 and 9 exists in `services/identity/src/identity/scope_admin.py` (`request_emergency`, `end_exception`, `sweep` with `review_overdue_48h` and `review_overdue_72h`), `db/policies/11_access.sql` (`app_emergency_cap` requires `w.emergency_access` and `o.kind in ('medical','both')`) and `libs/lmqa_models/src/lmqa_models/policy.py` (`emergency_duration`, `emergency_daily_limit`). Routes `POST /v1/emergency-access` and `DELETE /v1/emergency-access/{exception_id}` exist behind the disabled `matters_walls_tiers` flag. Criterion 4 (admin notice) uses `Notifier.enqueue`. Criterion 5: break-glass severity on queries is indicated by `app_access_basis` but not verified on the query path. No export endpoint exists (R-75).

### Requirement 8: Break-glass reading of private documents

**ID:** R-8 · **Type:** FR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §5.8, DEF-30, D2 · **Gates:** G5.6, G9.8

**User Story:** As a tenant, I want my private documents unreadable by my admin unless a governed flag and a recorded, time-boxed session both allow it, so that the privacy promise holds in the database.

#### Acceptance Criteria

1. WHEN an admin requests to enable `admin_can_read_private`, THE Identity_Service SHALL create a `private_read_enable` governance request with the Super Admin as second approver and a 24-hour wait.
2. WHEN a `private_read_enable` request executes, THE Identity_Service SHALL notify every tenant of the workspace.
3. IF an admin starts a break-glass session without a stated reason or without passing passkey step-up, THEN THE Identity_Service SHALL refuse the session.
4. WHEN an admin starts a break-glass session, THE Identity_Service SHALL set the session to expire at most 60 minutes after start.
5. THE Database SHALL allow an admin to read a private document only while `admin_can_read_private` is true for the workspace and the admin holds an active break-glass session.
6. THE Audit_Service SHALL include each break-glass session in the own audit history of each tenant who owns a private document read or returned in a query during that session (assumed default; not stated in design, see Q-30).

**Status:** Partial

**Evidence:** Criteria 1 to 5 have code: `services/identity/src/identity/scope_admin.py` (`start_break_glass`, `end_break_glass`, `private_read_enable_effect`, which inserts tenant notifications), rule 7 of `app_can_read` with `app_break_glass_active()` (`db/policies/11_access.sql`), `POST /v1/break-glass` with `step_up: true` in `contracts/authz-matrix.yaml`. All behind the disabled `matters_walls_tiers` flag and untested. Criterion 6 was not found in `services/audit/src/audit/service.py`, whose tenant scope covers own actions and documents shared with the tenant.

### Requirement 9: Owner-linked admin identities

**ID:** R-9 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin · **Design:** §5.9, DEF-13, D1 · **Gates:** G2.10

**User Story:** As a tenant, I want to be told when my workspace is administered by the organization owner's second identity, so that a weakened control is disclosed instead of hidden.

#### Acceptance Criteria

1. WHEN the Super Admin approves an admin, THE Identity_Service SHALL store whether the identity is declared owner-linked and SHALL write an audit event that links the approval to that flag.
2. WHILE a workspace's admin is owner-linked, THE Frontend SHALL show every tenant of that workspace the banner "This workspace is administered by the organization owner."
3. WHILE an organization has a co-owner, THE Identity_Service SHALL accept approval of an owner-linked admin only from the co-owner.
4. IF an owner-linked identity shares a verified email or a registered authenticator with the Super Admin identity, THEN THE Identity_Service SHALL reject the approval.

**Status:** Partial

**Evidence:** Only the data field exists: `memberships.owner_linked` in `db/migrations/0006_production_core.sql`, exposed in `principal_v` (`db/policies/11_access.sql`). No approval flow, banner or co-owner routing was found (`services/identity/src/identity/service.py`, `decide_admin`).

### Requirement 10: Lifecycle state machines as data

**ID:** R-10 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §3.1 principle 13, §6.1 to §6.8 · **Gates:** G1.9, G2.9, G9.9

**User Story:** As an engineer, I want every lifecycle declared once and enforced by the database, the services and generated tests, so that an application bug cannot skip a state.

#### Acceptance Criteria

1. THE Platform SHALL declare the membership, workspace, organization, document and index state, join code, governance request and access session lifecycles in `contracts/state-machines.yaml`, giving for each transition the allowed actors, guards and side effects, matching §6.2 to §6.8.
2. IF a state change on a stateful table is not declared, THEN THE Database SHALL reject the change through that table's transition table and trigger.
3. THE Platform SHALL generate the service-side transition guards from the declaration through the `lmqa_models` package.
4. THE Test_Suite SHALL run generated tests against the real database and API that expect every legal transition by an authorized actor to succeed, every legal transition by an unauthorized actor to fail with 404 or 403, and every illegal state pair to fail.
5. IF a user attempts to approve or change the user's own membership, THEN THE Identity_Service SHALL reject the request.
6. THE Database SHALL reject, through a CHECK constraint, any membership row whose approver is the member.
7. WHILE an organization is `pending`, THE Platform SHALL limit the organization's Super Admin to signing in, enrolling authenticators and viewing the status page.

**Status:** Partial

**Evidence:** Criterion 1 is partly met: the production machines (`membership`, `workspace`, `organization`, `document_lifecycle`, `join_code`, `governance_request`, `access_session`) are in `contracts/state-machines.yaml`, but they list states and actions without actors, guards or side effects. Criterion 2: `tools/state_machine_gen.py` generates `db/policies/40_transitions.sql` (`app_check_transition`, triggers on memberships, workspaces, organizations, documents, join_codes, governance_requests, access_exceptions, break_glass_sessions, operator grants); not applied to a database (`docs/production.md`). Criterion 3 is met for the MVP machines: `services/identity/src/identity/service.py` (`decide_admin`, `decide_member` call `transition`). Criterion 6: CHECK `memberships_no_self_approval` (`decided_by <> user_id`) in `db/migrations/0006_production_core.sql`; criterion 5 was not verified in the service layer. Criterion 4: no generated tests exist. Criterion 7: MVP organizations are created `active` (DEV-16). The MVP machines use `pending` instead of `pending_approval` and omit `removed` (DEV-17).

### Requirement 11: Common onboarding entry

**ID:** R-11 · **Type:** FR · **Priority:** P0 · **Persona:** New user · **Design:** §7.1 · **Gates:** G2.3, G8.2

**User Story:** As a new user, I want sign-up through Auth0 and a choice of three onboarding paths, so that my role is derived from the proof I submit and never from a field I control.

#### Acceptance Criteria

1. THE Auth0_Config SHALL require email verification and MFA enrollment for every user.
2. WHEN a user with no membership logs in, THE Frontend SHALL obtain an access token for the `onboarding` audience.
3. IF a token for the `onboarding` audience is presented on an endpoint that is not an onboarding endpoint, THEN THE Gateway SHALL reject the request.
4. THE Auth0_Config SHALL set the organization setting of API `main` to "require" and of API `onboarding` to "deny".
5. THE Frontend SHALL offer three onboarding cards (Create organization, Join as admin, Join as tenant) that select a flow only.
6. WHEN a user submits a code, THE Identity_Service SHALL derive the role from the kind of the valid code and from no client-supplied field.
7. THE Identity_Service SHALL add an admin or tenant to the Auth0 Organization, with the matching Auth0 role, only when the membership is approved.
8. WHEN a user's membership becomes `active`, THE Frontend SHALL start a new authorization request that names the user's Auth0 Organization and obtain a token carrying `org_id`.

**Status:** Partial

**Evidence:** Criteria 5 and 6 are met: `frontend/src/components/onboarding/onboarding.tsx` and `services/identity/src/identity/service.py` (`create_organization`, `join_admin`, `join_tenant`; the role comes from the code kind). Criteria 1 to 4 have configuration only: `infra/auth0/main.tf` defines `auth0_resource_server` `main` and `onboarding` and `auth0_guardian` MFA, but neither API sets organization required or denied, and the BFF client uses `organization_usage = "allow"`. The Gateway verifies one audience only (`libs/lmqa_auth/src/lmqa_auth/verifier.py`), and onboarding routes accept any authenticated token (`contracts/authz-matrix.yaml`, role `authenticated`). Criteria 7 and 8: `services/identity/src/identity/auth0_mgmt.py` (`add_member`, `assign_role`) exists but is enabled only with `AUTH0_ORGANIZATIONS=on` in the identity worker; feature `auth0_organizations` is off (DEV-10).

### Requirement 12: Organization creation and provisioning saga

**ID:** R-12 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin · **Design:** §7.2, §6.4, DEF-29, D9 · **Gates:** G2.1, G2.2

**User Story:** As a prospective customer, I want to create an organization that becomes usable only after every provisioning step succeeds, so that a half-built organization is never visible.

#### Acceptance Criteria

1. WHEN an onboarding-scope user submits an organization name, a deployment type (legal, medical, both) and a data region with an idempotency key, THE Identity_Service SHALL start a provisioning saga.
2. THE Identity_Service SHALL run the saga steps in order: organization row `pending` with a genesis audit entry; organization CMK with replica, key policy and deletion guards; control key with escrow copy; Auth0 Organization; registered resources, default policies and an active Super Admin membership; Super Admin added to the Auth0 Organization and marked privileged; organization `active`, or awaiting operator approval in production.
3. THE Identity_Service SHALL record the completion of each saga step so that a restarted saga resumes at the first incomplete step.
4. IF a saga step fails with a non-retryable error or fails on its 5th attempt with exponential backoff (attempt count configurable; assumed default; not stated in design, see Q-31), THEN THE Identity_Service SHALL compensate the completed steps in reverse order and leave the organization in state `pending` with no orphan Auth0 Organization or KMS key.
5. WHEN a request is replayed with an idempotency key already used, THE Identity_Service SHALL return the original result and create no new resource.
6. THE Identity_Service SHALL generate the Organization Code outside the saga, only when the Super Admin of an `active` organization with two registered authenticators requests it through `POST /v1/org/code`, and SHALL show the code once.
7. IF one IP address has created 3 organizations within the preceding rolling 24 hours (limit and window configurable; assumed default; not stated in design, see Q-32), THEN THE Identity_Service SHALL reject further organization creation requests from that IP address until the count in the window falls below the limit.
8. THE Auth0_Config SHALL block registration from disposable email domains through the `disposable-domain-block` pre-registration Action.

**Status:** Partial

**Evidence:** The MVP path partly meets criterion 6: `services/identity/src/identity/service.py` (`create_organization`) inserts the organization and an active Super Admin membership in one transaction, with status `active`, no region and no saga (DEV-16), and `generate_code` creates the code on request, but no two-authenticator check was found in it. Criteria 1 to 5 have code in `services/identity/src/identity/saga.py` (`OrganizationSaga` with steps `org_row`, `kms_key`, `audit_key`, `auth0_org`, `auth0_member`, `membership`, `activate`, plus `compensate`) and table `provisioning_sagas` (`db/migrations/0007_identity_production.sql`); no route starts it, and the identity worker only resumes stuck sagas (`services/identity/src/identity/worker.py`, `run_once`). The saga has no control-key escrow step. Criteria 7 and 8: per-IP limits and the `disposable-domain-block` Action were not found; `infra/auth0/actions/post-login.js` is the only Action. Verified email and MFA are covered by R-11; operator approval by criterion 2.

### Requirement 13: Admin joins an organization

**ID:** R-13 · **Type:** FR · **Priority:** P0 · **Persona:** Admin, Super Admin · **Design:** §7.3 · **Gates:** G2.3, G2.8

**User Story:** As a prospective admin, I want to request membership with the Organization Code and be activated only after the Super Admin approves, so that a leaked code cannot take over a workspace.

#### Acceptance Criteria

1. WHEN a user submits a valid Organization Code, THE Identity_Service SHALL create an admin membership in `pending_approval` and a workspace in `pending`.
2. WHEN the approver (the Super Admin, or the co-owner for owner-linked requests) approves an admin request with passkey step-up, THE Identity_Service SHALL move the workspace from `pending` through `provisioning` (partition, workspace content key, quotas) to `active`.
3. WHEN the approver approves an admin request, THE Identity_Service SHALL add the user to the Auth0 Organization with the `admin` role and set `app_metadata.privileged`.
4. WHEN the approver rejects an admin request, THE Identity_Service SHALL set the membership to `rejected`, revoke the user's sessions and remove the pending workspace.
5. WHILE a membership is `pending_approval`, THE Frontend SHALL show the user the "awaiting approval" page.
6. WHILE a membership is `pending_approval`, THE Platform SHALL give the user no data access and no organization-scoped token.
7. THE Identity_Service SHALL generate the Admin Code only when the new admin requests it through `POST /v1/workspace/code` after the admin's first privileged login, and SHALL show the code once.

**Status:** Partial

**Evidence:** Criteria 1, 4 (state part), 5, 6 (data access part) and 7 are met in the MVP: `services/identity/src/identity/service.py` (`join_admin`, `decide_admin`, `generate_code`), `frontend/src/components/onboarding/onboarding.tsx`. Criteria 2 and 3: the MVP uses state `pending`, moves the workspace straight to `active` with no `provisioning` step, no workspace key and no quotas, requires no step-up, and makes no Auth0 calls (DEV-16, DEV-29). The rejected workspace stays in state `rejected` instead of being removed (`contracts/state-machines.yaml`, `admin_membership.reject`).

### Requirement 14: Tenant joins a workspace

**ID:** R-14 · **Type:** FR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §7.4, D6 · **Gates:** G2.4

**User Story:** As a prospective tenant, I want to confirm which workspace I am joining before I spend a code use, so that I join the right admin's workspace.

#### Acceptance Criteria

1. WHEN a user previews a valid Admin Code, THE Identity_Service SHALL resolve code → workspace → admin → organization, return the admin's display name and leave the code's use count unchanged.
2. IF a user previews an invalid Admin Code, THEN THE Identity_Service SHALL return the same error as a failed join.
3. WHEN a user submits a valid Admin Code, THE Identity_Service SHALL create a `pending_approval` tenant membership.
4. WHEN an admin approves a tenant with a set of grants, THE Identity_Service SHALL make the membership `active` and apply the grants in the same step.
5. THE Identity_Service SHALL apply the workspace join policy to each tenant request: `manual` waits for the admin, `auto` approves on submission, and `domain_allowlist` approves on submission only when the user's email domain is on the workspace's list.
6. THE Identity_Service SHALL set the join policy of a new legal or medical workspace to `manual`.

**Status:** Partial

**Evidence:** Criteria 1, 2 and 3 are met (with state `pending`): `services/identity/src/identity/service.py` (`preview_tenant` with `consume=False`, `join_tenant`, shared `_redeem` raising `CodeInvalid`). Criteria 5 and 6 have columns only (`workspaces.join_policy`, `allowed_domains` in `db/migrations/0006_production_core.sql`); the MVP approves manually. Criterion 4 was not found in `decide_member`.

### Requirement 15: Co-owner

**ID:** R-15 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin · **Design:** §7.5, §6.7 `co_owner_set`, D14 · **Gates:** G2.10

**User Story:** As a Super Admin, I want to designate one co-owner through a cooled-off, passkey-accepted invite, so that two-person control and owner recovery have a customer-side second person.

#### Acceptance Criteria

1. WHEN a Super Admin invites a co-owner, THE Identity_Service SHALL create an invite bound to the invitee's email and a `co_owner_set` governance request.
2. IF an organization already has a co-owner, THEN THE Identity_Service SHALL reject a new co-owner invite.
3. WHEN the invitee accepts with passkey registration, THE Identity_Service SHALL start the 72-hour cooling-off at the acceptance (§6.7, acceptance is the approval that starts the wait), notify every admin of the organization at the acceptance (assumed default; not stated in design, see Q-34), and make the co-owner membership effective when the cooling-off ends.
4. THE Identity_Service SHALL give the co-owner the `super_admin` role.
5. IF a production organization has no co-owner 14 days after activation, THEN THE Platform SHALL prompt the Super Admin to designate one.
6. WHILE an organization has no co-owner, THE Identity_Service SHALL require the operator-verified second approver for `org_delete` and `successor_transfer`.

**Status:** Partial

**Evidence:** Criteria 3 and 4 have code: `co_owner_set_effect` in `services/identity/src/identity/lifecycle.py` and policy `co_owner_set_wait = 72 h` in `libs/lmqa_models/src/lmqa_models/policy.py`. No co-owner invite or accept route exists (`contracts/authz-matrix.yaml`), and the governance flag is off. Criteria 5 and 6 were not found; criterion 2 was not verified.

### Requirement 16: Join code format, storage and handling

**ID:** R-16 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin, Admin · **Design:** §7.6, DEF-11, DEF-29, D4 · **Gates:** G2.5

**User Story:** As a code owner, I want codes that resist guessing, are shown once, stored only as keyed hashes and leak as little as possible in handling, so that a leaked code is a nuisance and not a takeover.

#### Acceptance Criteria

1. THE Identity_Service SHALL generate Organization Codes of 64 characters (8-character lookup ID, 55 secret characters, 1 Luhn mod-32 check character) and Admin Codes of 32 characters (8, 23, 1) in upper-case Crockford Base32 from a CSPRNG, displayed in groups of 8.
2. THE Identity_Service SHALL store only a keyed HMAC-SHA-256 of kind plus full code under a versioned pepper held in the secret manager, plus the plaintext lookup ID, and SHALL show the plaintext once.
3. THE Identity_Service SHALL display, after creation, only the lookup ID, the creation and expiry dates and the uses remaining of a code.
4. THE Identity_Service SHALL apply default expiry and maximum uses of 30 days and 25 uses for Organization Codes and 90 days and 100 uses for Admin Codes.
5. WHEN a code is rotated, THE Identity_Service SHALL move the old code to `rotated` so that its next redemption fails, and SHALL leave requests made with the old code pending for re-review instead of approving them.
6. WHEN a code is verified, THE Identity_Service SHALL look it up by public ID and compare the HMAC in constant time.
7. IF a user fails 5 code attempts within 15 minutes, an IP address fails 20 attempts within one hour, or a lookup ID's circuit breaker is open (the breaker opens after 10 failed attempts on one lookup ID from any user or IP address within 15 minutes and closes 15 minutes after opening; values configurable; assumed default; not stated in design, see Q-33), THEN THE Identity_Service SHALL refuse further attempts from that user, IP address or lookup ID.
8. WHEN code verification fails for any reason, THE Identity_Service SHALL return the message "code invalid or expired" and record the true reason in the audit log only.
9. THE Frontend SHALL carry invite codes in the URL fragment, remove the fragment from history, post the code in a request body and send `Referrer-Policy: no-referrer` on onboarding pages.
10. THE Platform SHALL redact `code` fields from logs through the shared logging library.
11. WHEN a code is used for the first time from a new country, used in a burst, or used right after a failed-attempt spike, THE Identity_Service SHALL notify the code owner.
12. THE Identity_Service SHALL count a use only when a membership is created, and at most once per membership.

**Status:** Partial

**Evidence:** Criteria 1, 3, 4, 5 (old code revoked), 6, 9 and 12 are met in `libs/lmqa_security/src/lmqa_security/codes.py` (`generate`, `code_hmac`, `matches`, `luhn_valid`), `services/identity/src/identity/service.py` (`CODE_POLICY`, `generate_code`, `_redeem`), `frontend/src/lib/codes.ts`, `frontend/next.config.ts` (`Referrer-Policy: no-referrer`). Criterion 2 is partly met: the HMAC and versioned pepper exist, but the pepper comes from settings (`CODE_PEPPER_V1`), not a secret manager. Criterion 7 is partly met: per-user and per-IP limits exist as in-process `SlidingWindow` counters (not shared across replicas), with no per-lookup-ID circuit breaker (DEV-27). Criterion 8: one shared `CodeInvalid` error is returned; audit of the true reason was not verified. Criteria 10 and 11 were not found.

### Requirement 17: Lifecycle events and cascades

**ID:** R-17 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin, Admin · **Design:** §7.7, DEF-12 · **Gates:** G2.8

**User Story:** As an admin, I want every lifecycle event to have the immediate, data and code effects in §7.7, so that suspension, removal and freezing behave the same way everywhere.

#### Acceptance Criteria

1. WHEN the Super Admin suspends an admin, THE Identity_Service SHALL freeze the workspace, disable its Admin Code, suspend its active tenants with reason `workspace_frozen` and revoke their access within the R-23 SLO.
2. WHEN the Super Admin reactivates an admin, THE Identity_Service SHALL make the admin and workspace `active`, restore only cascade-suspended tenants and keep the Admin Code disabled until rotated.
3. WHEN the Super Admin removes an admin, THE Identity_Service SHALL set the workspace to `frozen` and start a 30-day decision window.
4. IF no successor is named within the 30-day decision window, THEN THE Platform SHALL set the workspace to `sealed`.
5. WHEN an admin suspends or removes a tenant, THE Identity_Service SHALL revoke the tenant's sessions and streams within the R-23 SLO and SHALL move the tenant's private documents to `held`.
6. THE Ingestion_Service SHALL show the workspace admin held documents as a metadata-only queue with ID, size, date and matter label, and with no title or text.
7. WHEN the workspace admin acts on a held document, THE Ingestion_Service SHALL let the admin either delete the document with its key destroyed or reassign it to another tenant on the same matter, without opening the document.
8. WHEN a tenant leaves or requests deletion, THE Platform SHALL close the membership and handle authored content per the retention schedule and legal hold.
9. WHEN an operator freezes an organization, THE Platform SHALL revoke all sessions, open a read-only export window and delete nothing.

**Status:** Partial

**Evidence:** In the MVP, suspending an admin sets the workspace `frozen` (`services/identity/src/identity/service.py`, `decide_admin`; `contracts/state-machines.yaml`), which denies tenants through rule 1, and suspending a tenant denies access at the next request. Cascade code for criteria 1 and 2 exists in `services/identity/src/identity/lifecycle.py` (`freeze_workspace_cascade`, `reactivate_workspace_cascade`) but is not called from the MVP path. Criteria 3 to 9 have no MVP route (no admin or tenant removal action); sealing after 30 days (criterion 4) is in `services/identity/src/identity/destruction.py` (`Lifecycle.tick`), flag-gated and untested. The held-documents queue (criteria 6 and 7) was not found.

### Requirement 18: Successor transfer

**ID:** R-18 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin · **Design:** §7.8, §5.3, DEF-54, D11 · **Gates:** G9.11

**User Story:** As a Super Admin whose admin left, I want to hand the frozen workspace to a new admin identity through a slow, loud, two-person process, so that tenants are neither stranded nor silently handed over.

#### Acceptance Criteria

1. WHEN the Super Admin issues a successor invite for a frozen workspace, THE Identity_Service SHALL create a join code of kind `successor` bound to the invitee's email and to that workspace.
2. WHEN the invitee submits the successor code, THE Identity_Service SHALL create a `pending_approval` membership linked to the frozen workspace without creating a second workspace.
3. WHEN the Super Admin starts a `successor_transfer` naming the pending successor membership, THE Identity_Service SHALL create the governance request with a 72-hour cooling-off and with the co-owner, or an operator `security_officer` after out-of-band confirmation, as second approver.
4. WHEN a `successor_transfer` request has its second approval and its 72-hour cooling-off has elapsed, THE Identity_Service SHALL re-parent the workspace to the successor, set the membership to `active`, reset `admin_can_read_private` to false, revoke every active break-glass session of the workspace, keep every wall of the workspace in force and bump the workspace scope version (§7.8; meaning of re-validate assumed; not stated in design, see Q-35).
5. WHEN a `successor_transfer` executes, THE Identity_Service SHALL notify every tenant of the workspace and the outgoing admin and SHALL write an audit event that the Super Admin cannot suppress.
6. IF no successor is named within 30 days, THEN THE Platform SHALL seal the workspace.

**Status:** Partial

**Evidence:** Criterion 1 has schema support: join code kind `successor` (`db/migrations/0006_production_core.sql`, `join_codes_kind_check`); `lmqa_security.codes.Kind` covers only `org` and `admin`. Criteria 3 to 5 are coded in `successor_transfer_effect` (`services/identity/src/identity/lifecycle.py`) and `KindRule` for `successor_transfer` (`services/identity/src/identity/governance.py`). Criterion 6 is coded in `services/identity/src/identity/destruction.py` (`Lifecycle`, `workspace_seal_after`). No successor invite route exists; the governance flag is off; nothing is tested.

### Requirement 19: Auth0 responsibility split and configuration as code

**ID:** R-19 · **Type:** IR · **Priority:** P0 · **Persona:** Engineer · **Design:** §8.1, §8.2, DEF-19, D8 · **Gates:** G0.7, G2.11

**User Story:** As a platform engineer, I want Auth0 to own authentication while PostgreSQL owns authorization, and every Auth0 setting to live in OpenTofu, so that tenants are reproducible and drift fails the build.

#### Acceptance Criteria

1. THE Platform SHALL keep role, workspace, status, grants, walls and approvals in the Database as the source of truth and use the Auth0 role only as a label.
2. THE Identity_Service SHALL create one Auth0 Organization per Organization and record its ID in `orgs.auth0_org_id`.
3. THE Identity_Service SHALL be the only component that assigns the three Auth0 roles (`super_admin`, `admin`, `tenant`) that are defined once per Auth0 tenant.
4. THE Auth0_Config SHALL define the four tenants `dev`, `ci`, `staging` and `prod` in `infra/auth0/`, each with: API `main` (RS256, organization required, 10-minute access tokens, refresh-token rotation with reuse detection); API `onboarding` (organization denied); a Regular Web Application `web-bff` with Authorization Code plus PKCE and exact-match callback and logout URLs; an `identity-m2m` client with only the listed Management API scopes; a database connection with passkeys, breached-password detection and no social connections for legal and medical deployments; MFA "always" with WebAuthn, TOTP and recovery codes and with SMS, voice and email OTP disabled; and the Actions `enforce-auth-strength`, `block-unverified-email` and `disposable-domain-block`.
5. THE Auth0_Config SHALL define Actions that make no call to the Platform's backend.
6. THE Toolchain SHALL run `tofu plan` in CI against each of the four Auth0 tenants.
7. IF `tofu plan` in CI reports drift for an Auth0 tenant, THEN THE Toolchain SHALL fail the CI job.
8. WHERE a deployment processes PHI, THE Platform SHALL run on an Auth0 Enterprise plan with the HIPAA BAA add-on, confirmed with the vendor (plan, region, add-on) before the first real clinical document is processed.

**Status:** Partial

**Evidence:** Criterion 1 is met (role, status and workspace come from PostgreSQL in `services/identity/src/identity/service.py`, `resolve`). Criterion 4 is partly met by `infra/auth0/main.tf` (`auth0_tenant`, `auth0_guardian` with `email = false`, `auth0_attack_protection` with breached-password detection, `auth0_connection` with passkeys, `auth0_resource_server` `main` and `onboarding`, `auth0_client` `bff`, `auth_harness` and `identity_m2m`, `auth0_role`, one post-login Action) for a single `var.env`; organization required and denied are not set, and only the post-login Action exists. Criterion 5 is met (`infra/auth0/actions/post-login.js` makes no backend calls). Criteria 2 and 3 have code in `services/identity/src/identity/saga.py` and `auth0_mgmt.py`, flag off. Criteria 6 and 7: no CI workflow runs `tofu plan` (`.github/workflows/secret-scan.yml` is the only workflow). Criterion 8 is an external item (D8, open question Q-08).

### Requirement 20: Login flow and server-side BFF sessions

**ID:** R-20 · **Type:** FR · **Priority:** P0 · **Persona:** All users · **Design:** §8.3, §4.8, §17.3, DEF-09, DEF-58, D30 · **Gates:** G8.5

**User Story:** As a user, I want my tokens to stay on the server and my session to be revocable centrally, so that stolen browser state cannot be replayed.

#### Acceptance Criteria

1. THE Frontend SHALL authenticate through `@auth0/nextjs-auth0` v4 with Authorization Code plus PKCE as a Regular Web Application.
2. THE Frontend SHALL store sessions in a Valkey-backed server-side session store, encrypted with the session secret.
3. THE Frontend SHALL give the browser only an opaque, httpOnly, SameSite session ID, with no token in browser storage, in any cookie value or in any response body.
4. WHEN a session is deleted from the session store, including through "sign out everywhere" or revocation, THE Frontend SHALL reject the next request that carries that session ID.
5. THE Frontend SHALL send the access token for the `main` audience to the Gateway only.
6. THE Gateway SHALL resolve role, workspace, status and grants from Valkey and the Database on every request and SHALL use the token's role claim only as a routing hint for the Frontend.
7. IF the token's role claim differs from the role in the Database, THEN THE Gateway SHALL deny the request and raise an alert.
8. THE Auth0_Config SHALL keep PHI, matter names and patient identifiers out of Auth0 profile fields and claims.

**Status:** Partial

**Evidence:** Criteria 1 and 5 are met: `frontend/src/lib/auth0.ts` (`Auth0Client`, `enableAccessTokenEndpoint: false`), `frontend/src/app/api/backend/[...path]/route.ts` (token attached server-side). Criteria 2 and 3 are coded in `frontend/src/lib/session-store.ts` (`ValkeySessionStore`) but enabled only with `FEATURE_SERVER_SIDE_SESSIONS=on`; the default is the SDK's encrypted cookie session (DEV-11). Criterion 6 is met for PostgreSQL: the Gateway resolves from PostgreSQL on every request. Criterion 7 is not met: `role_claim` parsed in `libs/lmqa_auth/src/lmqa_auth/verifier.py` is never compared (DEV-30). Criteria 4 and 8 were not verified in code.

### Requirement 21: Authentication strength and session limits

**ID:** R-21 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin, Admin, Tenant · **Design:** §8.4, D13 · **Gates:** G2.6, G2.7

**User Story:** As a security officer, I want the highest-power accounts to use phishing-resistant authentication and shorter sessions, so that account takeover is hardest where it matters most.

#### Acceptance Criteria

1. WHEN a person becomes a Super Admin or admin, THE Identity_Service SHALL set `app_metadata.privileged = true` through the Management API, and THE Auth0_Config post-login Action SHALL enroll or challenge a WebAuthn factor for privileged users.
2. THE Auth0_Config post-login Action SHALL compute `auth_strength` as `passkey`, `webauthn_mfa`, `otp_mfa` or `password` from the authentication methods Auth0 records, and THE Gateway SHALL reject a privileged principal whose strength is `otp_mfa` or `password`.
3. THE Gateway SHALL require privileged users to hold at least two registered phishing-resistant authenticators and a fresh authentication within 5 minutes for governance actions and code generation.
4. THE Identity_Worker SHALL sync authenticator counts from the Management API, and THE Gateway SHALL expose `has_backup_authenticator` in `GET /v1/me`.
5. IF a privileged user loses every authenticator, THEN THE Platform SHALL refuse self-recovery with a password or TOTP and SHALL route recovery to `owner_recovery` or to an admin re-onboarding path with a 72-hour wait, identity verification and notice to the co-owner and admins.
6. THE Frontend SHALL apply a 15-minute idle timeout and an 8-hour absolute limit to privileged sessions and a 30-minute idle timeout and a 12-hour absolute limit to tenant sessions, which organizations may tighten.
7. THE Test_Suite SHALL pin the authentication method names the Action observes with a contract test against the real tenant.

**Status:** Partial

**Evidence:** Criterion 1 is partly met: `infra/auth0/actions/post-login.js` enforces MFA or a WebAuthn challenge when `app_metadata.privileged` is true; `Auth0Management.set_app_metadata` exists (`services/identity/src/identity/auth0_mgmt.py`) but nothing sets the flag in the MVP path. Criterion 2: the Action emits `otp`, `mfa`, `passkey` or `passkey_mfa` (names differ from the design), and the Gateway checks strength only on `step_up` routes (`services/gateway/src/gateway/app.py`, `needs_step_up`). Criterion 7 has a fixture only: `contracts/claims/auth-methods.json`. Criterion 6 is not met: `frontend/src/lib/auth0.ts` sets 30 minutes idle and 8 hours absolute for everyone (DEV-28). Criteria 3, 4 and 5 were not found.

### Requirement 22: Gateway token verification

**ID:** R-22 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §8.5 · **Gates:** G3.1, G3.2

**User Story:** As a security reviewer, I want the Gateway to accept only correctly signed, current access tokens for our API from allowed clients and organizations, so that token abuse is rejected uniformly.

#### Acceptance Criteria

1. THE Gateway SHALL verify token signatures against the cached Auth0 JWKS, refresh the JWKS on an unknown `kid` with a rate limit, accept only RS256 and reject `none` and HS256.
2. THE Gateway SHALL require `iss` to equal the tenant domain exactly, `aud` to equal the API identifier and `azp` to be an allowed client.
3. THE Gateway SHALL check `exp` and `nbf` with at most 30 seconds of clock skew.
4. THE Gateway SHALL require an `org_id` claim equal to the organization of the user's active membership.
5. IF any token check fails, THEN THE Gateway SHALL return 401 with a uniform body.

**Status:** Partial

**Evidence:** Criteria 1, 3 and 5 are met in `libs/lmqa_auth/src/lmqa_auth/verifier.py` (`TokenVerifier.verify`: RS256 only, `PyJWKClient` cache, `leeway=30`, required claims) and `services/gateway/src/gateway/app.py` (`guard` returns a uniform 401). Criterion 2 is met for `iss` and `aud`; `azp` is not checked. Criterion 4 is not met: `org_id` is parsed but never compared (DEV-30). Access-token lifetime of 600 seconds is set in `infra/auth0/main.tf`.

### Requirement 23: Suspension and revocation within seconds

**ID:** R-23 · **Type:** NFR · **Priority:** P0 · **Persona:** Admin, Super Admin · **Design:** §8.6, DEF-07 · **Gates:** G2.12, G3.4

**User Story:** As an admin who suspends someone, I want the suspended user's new requests and open streams stopped within seconds, so that a JWT's remaining lifetime does not matter.

#### Acceptance Criteria

1. WHEN a membership is suspended or removed, THE Identity_Service SHALL set the state and increment `principal_version` in one transaction.
2. WHEN `principal_version` changes, THE Identity_Service SHALL delete the principal from the shared Valkey cache and publish an invalidation message, and THE Gateway SHALL keep an in-process copy for at most 5 seconds with every shared-cache entry expiring within 30 seconds.
3. IF Valkey is unreachable, THEN THE Gateway SHALL read the Database directly or deny the request, and SHALL never serve a stale principal.
4. WHEN a membership is suspended or removed, THE Identity_Service SHALL call the Auth0 Management API to remove the Organization membership or block the user, delete refresh tokens and end sessions.
5. THE Gateway SHALL reject new requests from a suspended user within 2 seconds at p99 while pub/sub is healthy and within 5 seconds while pub/sub is down.
6. THE Gateway SHALL cut an open SSE stream within 2 seconds of the invalidation message and within 15 seconds through a periodic status poll as fallback.

**Status:** Partial

**Evidence:** Criterion 1 is met in the database: trigger `principal_version_bump` with `pg_notify('lmqa_revocation', ...)` in `db/policies/11_access.sql` (migration not applied). In the MVP, every request resolves the principal from PostgreSQL (`IdentityService.resolve`), so a suspension applies on the next request, which satisfies criteria 3 and 5 for requests without any cache. Criteria 2 and 6 have code: `PrincipalCache`, `RevocationConsumer` and stream registration in `services/gateway/src/gateway/trust.py`, used only by the flag-gated streaming route. Criterion 4 has code in `services/identity/src/identity/lifecycle.py` (`Revoker.fan_out`) and `auth0_mgmt.py` (`revoke_user_sessions`); `Revoker` is not referenced outside its module. No timing test exists.

### Requirement 24: Step-up authentication

**ID:** R-24 · **Type:** FR · **Priority:** P0 · **Persona:** Super Admin, Admin, Tenant · **Design:** §8.7, §15.1 · **Gates:** G2.6, G3.8

**User Story:** As a security officer, I want sensitive actions to require a fresh, strong authentication, so that an idle stolen session cannot perform them.

#### Acceptance Criteria

1. THE Gateway SHALL require Step_Up (fresh authentication within 5 minutes, at strength `passkey` or `webauthn_mfa` for privileged roles) to generate or rotate either code, approve or remove an admin, remove a tenant, change policy flags, start break-glass, approve any governance request or export audit data.
2. WHEN Step_Up is needed, THE Gateway SHALL answer HTTP 401 with `WWW-Authenticate: Bearer error="insufficient_user_authentication"` and a `max_age` hint (RFC 9470).
3. WHEN the Frontend receives a step-up challenge, THE Frontend SHALL start a new authorization request with `max_age`, and THE Auth0_Config Action SHALL enforce the required factor.

**Status:** Partial

**Evidence:** Criterion 2 is met: `services/gateway/src/gateway/trust.py` (`needs_step_up`, `step_up_challenge`). Criterion 3 is partly met: `frontend/src/lib/api-client.ts` handles `insufficient_user_authentication`, and the Action challenges WebAuthn when `step_up` is requested. Criterion 1 is not met: only the flag-gated routes marked `step_up: true` in `contracts/authz-matrix.yaml` (governance create and decide, break-glass start) enforce it; `POST /v1/org/code`, `POST /v1/workspace/code` and `POST /v1/org/admins/{membership_id}/{action}` do not (DEV-29).

### Requirement 25: Isolation of the Auth0 Management API

**ID:** R-25 · **Type:** IR · **Priority:** P0 · **Persona:** Engineer · **Design:** §8.8 · **Gates:** G2.11

**User Story:** As a security officer, I want the credential that can mint admins held by one service with minimal scopes and watched hourly, so that its compromise is contained and detected.

#### Acceptance Criteria

1. THE Identity_Service SHALL be the only component holding the Management API machine-to-machine credentials, in its own secret, rotated on a schedule.
2. THE Identity_Service SHALL refuse to use a Management API token whose scopes exceed the listed minimum.
3. THE Platform SHALL allow Management API egress from the Identity_Service only.
4. THE Identity_Worker SHALL run an hourly reconciliation and SHALL raise an alert for any admin or Super Admin role assignment in Auth0 that has no approved membership in the Database.

**Status:** Partial

**Evidence:** Criteria 2 and 4 have code: `services/identity/src/identity/auth0_mgmt.py` (`SCOPES`, `verify_scopes`), `services/identity/src/identity/lifecycle.py` (`reconcile_auth0_roles`) called hourly by `services/identity/src/identity/worker.py` (`RECONCILE_EVERY = 3600`) when `AUTH0_ORGANIZATIONS=on`. Criterion 1: M2M variables are listed in `.env.example` and read by the identity worker; rotation was not found. Criterion 3: no egress rule exists (Compose networks are not defined in `compose.yaml`).

### Requirement 26: SSO and automatic membership

**ID:** R-26 · **Type:** IR · **Priority:** P1 · **Persona:** Super Admin · **Design:** §8.9 · **Gates:** G2.3

**User Story:** As a hospital or law-firm owner connecting our own identity provider, I want SSO users to still go through codes and approval, so that SSO never silently adds every employee.

#### Acceptance Criteria

1. THE Auth0_Config SHALL keep Auth0's automatic-membership option off for every organization connection.
2. WHEN a user arrives through SSO without a membership, THE Frontend SHALL route the user to onboarding.
3. THE Identity_Service SHALL match accounts by connection and subject, never by email, and THE Auth0_Config SHALL disable automatic account linking.
4. WHERE an SSO-backed user is privileged, THE Auth0_Config Action SHALL require the organization's identity provider to assert phishing-resistant authentication, and IF the assertion is missing, THEN THE Action SHALL require a WebAuthn factor registered in Auth0.

**Status:** Partial

**Evidence:** Criterion 2 is met by the general flow: any user without a membership is sent to `/onboarding` (`frontend/src/app/(super-admin)/layout.tsx` and the other role layouts redirect when `membership.active` is false). Users are keyed by `auth0_sub` (`db/migrations/0001_schema.sql`), which partly meets criterion 3. No SSO connection configuration, auto-membership setting or account-linking setting was found in `infra/auth0/main.tf`; criterion 4 was not found in the Action.

### Requirement 27: Testing identity for real

**ID:** R-27 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §8.10, DEF-10, DEF-57 · **Gates:** G0.7, G2.7

**User Story:** As an engineer, I want identity tests to run against a real Auth0 tenant with real passkeys and mailboxes, so that tests prove the production behavior.

#### Acceptance Criteria

1. THE Test_Suite SHALL drive real sign-up through Universal Login with Playwright and a Chromium virtual WebAuthn authenticator, and SHALL read verification emails from real mailboxes on a project-owned domain over IMAP.
2. THE Test_Suite SHALL log in once per role per worker with session-scoped fixtures and reuse refresh-token rotation to stay within the `ci` tenant's rate limits.
3. THE Test_Suite SHALL include a claim-shape snapshot test that pins the token structure and the method names the Action observes.
4. THE Platform SHALL provide `tools/auth_harness`, a minimal real Authorization Code plus PKCE relying party registered in the tenant, for backend stages before the Frontend exists.
5. THE Platform SHALL use no mock identity provider in any test or demo.

**Status:** Partial

**Evidence:** Criterion 4 is met in code: `tools/auth_harness.py` and the `auth0_client.auth_harness` resource in `infra/auth0/main.tf`. Criterion 3 has a fixture (`contracts/claims/auth-methods.json`) but no test. Criteria 1 and 2: no Playwright or IMAP test exists. Criterion 5 is not met: `README.md` states that `make demo` and `make demo-web` simulate the Auth0 login with tokens signed by a throwaway local key (`tools/demo.py`, `tools/demo_web.py`) (DEV-35).

### Requirement 28: Context tokens and signer certificates

**ID:** R-28 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §9.1, DEF-26, DEF-39, DEF-49, D29 · **Gates:** G3.3, G3.5

**User Story:** As a service owner, I want each internal call to carry a short-lived, single-audience token minted only by the Gateway, so that services can re-check permissions without ever seeing the user's Auth0 token.

#### Acceptance Criteria

1. WHEN the Gateway calls an internal service, THE Gateway SHALL mint an ES256 Context_Token for that one audience, valid for 60 seconds at the start of the call, carrying `sub`, `org_id`, `workspace_id`, `role`, `auth_strength`, `scope_hash`, `scope_version`, `pv`, `request_id` and `jti`, with `scope_hash` and `scope_version` read from `principal_v`.
2. THE Gateway SHALL never forward the Auth0 token to an internal service.
3. WHEN a service receives a Context_Token, THE service SHALL verify signature, audience, expiry and issuer against the internal trust bundle, build its database context from the claims only, and reject a wrong audience, an old issue time or, on state-changing calls, a reused `jti`.
4. THE Gateway SHALL generate an in-memory ES256 key pair every hour and obtain a Signer_Certificate signed by a KMS asymmetric trust root (never exported, rotated every 90 days with overlap) binding the public key to the instance's workload identity for at most one hour.
5. THE services SHALL fetch and cache Signer_Certificates, verify the KMS signature and consult a deny-list in Valkey.
6. WHILE long-running work (ingestion jobs, open streams) runs, THE service SHALL compare the `pv` claim with the current value at checkpoints and abort on a mismatch.
7. IF a token verifies but was minted outside the Gateway's identity, or certificate issuance spikes, THEN THE Platform SHALL raise an alert.

**Status:** Partial

**Evidence:** Criteria 3, 4 and 5 are coded in `libs/lmqa_auth/src/lmqa_auth/context.py` (`Signer`, `SignerCertificate`, `ContextMinter`, `ContextVerifier` with deny list, `ReplayCache`, `KmsTrustRoot`, `LocalTrustRoot`) and `libs/lmqa_auth/src/lmqa_auth/internal.py` (`context_dependency`). Criterion 6 is coded in `libs/lmqa_db/src/lmqa_db/service.py` (`StalePrincipalError`) and the ingestion envelope check. Criterion 2 holds because no internal network call exists. Criterion 1 is not met: `services/gateway/src/gateway/production.py` (`context_for`) mints with `scope_hash=""`, `scope_version=0`, `pv=0` and `auth_strength="unknown"`, verifies the token in the same process and discards it; the default trust root is a per-process `LocalTrustRoot`, not KMS (DEV-12). Criterion 7 was not found.

### Requirement 29: Per-service credentials

**ID:** R-29 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §9.2, DEF-10 · **Gates:** G1.2, G5.2

**User Story:** As a security reviewer, I want each service to hold its own narrowly scoped credentials, so that one compromised container cannot impersonate other services or users.

#### Acceptance Criteria

1. THE Platform SHALL authenticate service-to-service calls with a distinct per-service secret locally and with mTLS client certificates using workload identity in production.
2. THE Database SHALL give each service its own non-owner `NOBYPASSRLS` login role created by the init script.
3. THE Platform SHALL give `retrieval` a read-only Qdrant key and `ingestion` a read-write Qdrant key, held in the secret manager in production.
4. THE Platform SHALL give each service a Valkey ACL user with key-prefix permissions.
5. THE Platform SHALL give object-store credentials to `ingestion` only, limited by prefix.
6. THE Platform SHALL give each service KMS permissions only as listed in §4.2, with key policy conditions on encryption context.

**Status:** Partial

**Evidence:** Criteria 3 and 4 are met in the infrastructure: `compose.yaml` (Qdrant `API_KEY` and `READ_ONLY_API_KEY`; Valkey ACL file), `tools/infra_config.py`, and the tests `test_qdrant_keys_are_enforced` and `test_valkey_key_patterns_confine_each_service` in `tests/integration/test_stage0_infra.py` (22 passed per `docs/production.md`). Criterion 2 is coded (`svc_*` roles in `db/roles/grants.sql`, `ServiceDatabase` in `libs/lmqa_db/src/lmqa_db/service.py`), but the running MVP uses `lmqa_app` and `lmqa_system` (BYPASSRLS) (DEV-13). Criterion 5: `OBJECT_STORE_CREDS_INGESTION` appears in `.env.example`; the MVP writes to local disk. Criterion 1: `libs/lmqa_auth/src/lmqa_auth/internal.py` exists; no internal endpoints use it. Criterion 6 was not found outside `infra/keyguard/key-policy.json.tftpl`.

### Requirement 30: Signed job envelope

**ID:** R-30 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §9.3, §10.8, DEF-53 · **Gates:** G0.13, G4.7

**User Story:** As an engineer, I want every background job to carry a signed, expiring envelope created in the same transaction as its document, so that a worker never acts on a forged, stale or orphaned job.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL attach to each job an envelope with `org_id`, `workspace_id`, `owner_user_id`, `doc_id`, `doc_version`, `visibility`, an expiry, the enqueuing principal's `pv` and a signature by the enqueuing service's certified key.
2. THE Ingestion_Service SHALL insert the job row in the same database transaction as the document row by calling the queue's SQL defer function.
3. WHEN a worker picks up a job, THE worker SHALL verify the envelope's signature and expiry and re-validate against the Database that the document, owner and workspace are still active, and IF any check fails, THEN THE worker SHALL abort and log.

**Status:** Partial

**Evidence:** All three criteria are coded in `services/ingestion/src/ingestion/production.py` (`defer_ingest` calls `procrastinate_defer_jobs_v2` with an envelope from `sign_envelope`; `IngestJob.run` calls `verify_envelope` and `_still_valid`), and transactional defer through PgBouncer is proven by `tests/integration/test_stage0_queue_spike.py` (4 passed). The MVP request path does not use it: uploads run on the in-process `Ingestor` thread (`services/ingestion/src/ingestion/pipeline.py`) with no envelope (DEV-23).

### Requirement 31: Retrieval ledger

**ID:** R-31 · **Type:** DR · **Priority:** P0 · **Persona:** Engineer · **Design:** §9.4, §4.4 rule 1, DEF-15, DEF-63 · **Gates:** G5.10

**User Story:** As an auditor, I want an immutable record of what retrieval returned for each request, so that the Validator checks against a record the Gateway cannot alter and audit can prove what was retrieved.

#### Acceptance Criteria

1. THE Retrieval_Service SHALL be the only writer of `retrieval_records` (insert-only grant), and THE Generation_Service and THE Validator SHALL have select-only grants.
2. THE Database SHALL scope ledger reads to the same workspace and to the `user_id` that made the request.
3. THE Retrieval_Service SHALL record per request the `request_id`, the principal's `user_id` and `scope_hash`, and per chunk the chunk ID, chunk version, content SHA-256, rank, scores, request-local alias and whether the trim step dropped it.
4. THE Generation_Service SHALL show the model only aliases, never global chunk IDs.
5. THE Gateway SHALL hand off between services through the ledger so that chunk text never travels through the Gateway.

**Status:** Partial

**Evidence:** Criterion 2 is met: policy `retrieval_records_own` follows `queries_own` (user and workspace) in `db/policies/20_rls.sql`. Criterion 4 is met: aliases `S1…Sn` (`services/generation/src/generation/prompts.py`; `docs/mvp.md`). Criterion 3 is mostly met by `RetrievalService.record_ledger` (`services/retrieval/src/retrieval/service.py`), with dropped candidates and reasons; `scope_hash` is not recorded in the MVP. Criterion 1 is not met: `lmqa_app` holds `select, insert` on `retrieval_records` for every caller (`db/roles/grants.sql`), and the ledger is written by the Gateway's query flow transaction. Criterion 5 is not met: all services run inside the Gateway process (DEV-01).

### Requirement 32: Layered isolation and PostgreSQL enforcement

**ID:** R-32 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §3.1 principles 1 and 3, §10.1, §10.3, DEF-01, DEF-44, DEF-52, DEF-53 · **Gates:** G1.2, G1.3, G1.7, G1.8

**User Story:** As a security reviewer, I want every boundary enforced at least twice with PostgreSQL as the last word, so that one failing layer cannot expose another scope's data.

#### Acceptance Criteria

1. THE Platform SHALL enforce isolation in five layers (browser and BFF for experience only; Gateway; services; PostgreSQL as final authority; vector store, object store and Valkey as narrowing; detection), and SHALL not treat the shared vector collection as a boundary.
2. THE Database SHALL use `FORCE ROW LEVEL SECURITY` on every table, non-owner `NOBYPASSRLS` service roles, a separate migration owner role held by no service, and the dedicated roles `identity`, `gateway` (`principal_v` only), `retrieval`, `generation`, `validator`, `ingestion`, `audit_reader`, `reconciler` (column-level SELECT on IDs and index metadata), `ops_metadata_ro` and `audit_writer` (EXECUTE on `audit_append` only).
3. THE Platform SHALL set context per transaction with `set_config(..., true)` and THE scoped session in `lmqa_db` SHALL refuse to execute without a context.
4. THE Database SHALL read context settings as `NULLIF(current_setting(..., true), '')` in every policy so that an unset context matches no row on a reused pooled connection.
5. WHEN a service starts, THE service SHALL run a boot self-test (no context returns zero rows; another workspace's context returns zero rows) and IF the self-test fails, THEN THE service SHALL refuse to start.
6. THE Database SHALL implement grant, wall, exception and break-glass lookups as `STABLE` helper functions owned by a non-login `policy_helper` role that take identity only from the transaction context.
7. THE Platform SHALL route request-path connections through PgBouncer in transaction mode, ban session `SET`, session advisory locks, `LISTEN`/`NOTIFY` and long-lived cursors on the request path by a CI scan of every SQL string and a boot check, and SHALL connect workers, the indexer listener and migrations directly to PostgreSQL.
8. THE Database SHALL provide composite indexes `(workspace_id, user_id, matter_id)` on grants and walls, `(workspace_id, matter_id, visibility, owner_user_id)` on documents and chunks, and partial indexes on active exceptions and sessions.
9. THE Database SHALL grant no service role INSERT, UPDATE or DELETE on audit tables; audit writes SHALL go through the `SECURITY DEFINER` function `audit_append`.

**Status:** Partial

**Evidence:** Criterion 3 is met: `libs/lmqa_db/src/lmqa_db/database.py` (`Database.scoped`) and `service.py` (`ServiceDatabase.scoped`). Criterion 4 is met: `app_user_id()` uses `nullif(current_setting('app.user_id', true), '')` (`db/policies/10_helpers.sql`). Criterion 9 is met for the MVP roles (`db/roles/grants.sql` grants only EXECUTE on `audit_append`). Criterion 2 is coded in `db/policies/15_force_rls.sql` (FORCE on every table) and `db/roles/grants.sql` (`svc_*` roles), but the running roles are `lmqa_app` and `lmqa_system` with BYPASSRLS (DEV-13). Criterion 5 is coded in `app_boot_self_test()` and `ServiceDatabase.boot_self_test`; the MVP `Database` does not call it. Criterion 6 differs: helpers are `SECURITY DEFINER` functions owned by `lmqa_owner`, not a `policy_helper` role. Criterion 7: PgBouncer runs (`compose.yaml`) and `test_pgbouncer_transaction_pooling_keeps_context_transaction_local` passed; no SQL-string scan exists. Criterion 8 is partial (`matter_grants_user`, `matter_walls_user`, `documents_matter` indexes). Criterion 1's detection layer is R-63.

### Requirement 33: Partition key per store

**ID:** R-33 · **Type:** DR · **Priority:** P0 · **Persona:** Engineer · **Design:** §10.2 · **Gates:** G4.1, G5.1

**User Story:** As an engineer, I want each store partitioned by organization and workspace with server-built keys, so that a client can never name another scope's data.

#### Acceptance Criteria

1. THE Database SHALL partition by `org_id`, `workspace_id`, owner and matter with FORCE RLS and composite foreign keys.
2. THE Vector_Library SHALL index `workspace_id` as a tenant payload field (`is_tenant`) in one collection per embedding version, building filters only from a principal.
3. THE Object_Store_Library SHALL build object keys `org_{id}/ws_{id}/doc_{id}/v{n}` from database rows, never from client input, and SHALL issue presigned URLs valid for 60 seconds or less.
4. THE Platform SHALL prefix Valkey keys `o:{org}:w:{ws}:…` with an ACL user per service, scope-hashed cache keys and TTLs.
5. THE Database SHALL keep one audit chain per workspace and one control-plane chain per organization.
6. THE Generation_Service SHALL apply the organization's LLM provider setting under a no-retention contract.

**Status:** Partial

**Evidence:** Criterion 1 is met (R-1). Criterion 3 is met for keys in `libs/lmqa_objectstore/src/lmqa_objectstore/__init__.py` and `s3.py` (`final_key`, `quarantine_key`, 60-second presign), with S3 behind the disabled `object_store` flag. Criterion 2 is coded in `libs/lmqa_vectorstore/src/lmqa_vectorstore/qdrant.py`, flag off. Criterion 4 is partly met: ACL users per service are tested (`tests/integration/test_stage0_infra.py`); the scope-hashed cache is unwired (R-37). Criterion 5 is not met: chains are per organization (DEV-18). Criterion 6 is not met: the provider is global (DEV-31).

### Requirement 34: Fail-closed behavior on dependency failure

**ID:** R-34 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §3.1 principle 10, §10.4 · **Gates:** G3.10, G5.12, G10.5

**User Story:** As a security officer, I want the system to stop instead of degrading into unaudited or unauthorized behavior when a dependency fails, so that outages never become leaks.

#### Acceptance Criteria

1. IF Auth0 is unreachable, THEN THE Platform SHALL let existing sessions continue until their limits, fail new logins and allow no anonymous access.
2. IF Valkey is unreachable, THEN THE Gateway SHALL read the Database directly, degrade rate limits to a conservative local limit and bypass the answer cache.
3. IF Qdrant is unreachable, THEN THE Retrieval_Service SHALL return 503 with no keyword-scan fallback.
4. IF KMS is unreachable, THEN THE Key_Ring SHALL keep cached workspace keys working for at most 15 minutes and then fail closed, while already-issued Signer_Certificates work until they expire.
5. IF PostgreSQL is unreachable, THEN THE Platform SHALL stop all request processing.
6. IF an audit write fails, THEN THE Gateway SHALL stop the stream and release nothing further.
7. IF the LLM provider fails, THEN THE Generation_Service SHALL fail the query with a clear error and SHALL switch to another provider only when the organization configured that fallback.
8. IF the Validator is unavailable, THEN THE Gateway SHALL release no sentence and fail the query.

**Status:** Partial

**Evidence:** Criterion 5 is met: `services/gateway/src/gateway/app.py` maps `psycopg.OperationalError` to 503. Criterion 6 is met in the MVP buffered flow (`services/gateway/src/gateway/query_flow.py`: query, ledger and audit commit in one transaction before release) and coded for streaming in `services/gateway/src/gateway/stream.py`. Criterion 8 is met because the validator runs in-process and its failure fails the request. Criterion 2: `RateLimiter._allow_local` exists in `services/gateway/src/gateway/trust.py`. Criterion 3: `services/retrieval/src/retrieval/vector_search.py` documents a 503 with no fallback (flag off). Criterion 4: `DekCache` with 15-minute TTL in `libs/lmqa_keys/src/lmqa_keys/keyring.py` (flag off). Criterion 7 is not met: `services/generation/src/generation/llm_client.py` falls back across providers through the global `LLM_FALLBACK_MODELS` chain (DEV-31). Criterion 1 was not tested.

### Requirement 35: Vector search isolation

**ID:** R-35 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §10.5, DEF-01, DEF-14, DEF-47, D16 · **Gates:** G5.1, G5.2, G5.4, G5.9

**User Story:** As a security reviewer, I want vector search to narrow candidates only through a principal-built filter and every hit re-checked in PostgreSQL, so that a filter bug cannot leak another scope's chunks.

#### Acceptance Criteria

1. THE Vector_Library SHALL be the only code that reaches Qdrant; its query, delete-by-filter and payload-update functions SHALL require a principal or the workspace filter and SHALL have no unfiltered variant, and point lookups by ID SHALL never use user-supplied IDs.
2. THE Vector_Library SHALL always include `org_id` and `workspace_id` in filters; for tenants `(owner = me) OR (visibility = matter AND matter_id IN allowed AND tier ≤ max)` with `must_not` on walled matters; for admins `(owner = me) OR visibility = matter`, plus private documents only when the flag and an active break-glass session allow it; plus the matters of active emergency exceptions.
3. IF no filter can be built, THEN THE Retrieval_Service SHALL answer 403 and run no search.
4. WHEN Qdrant returns chunk IDs, THE Retrieval_Service SHALL fetch chunk text from the Database under RLS, drop any ID the Database refuses, count it in a mismatch metric, and raise a high-severity alert when the Reconciler finds the ID belongs to another scope.
5. WHERE an organization requires the vector store itself to enforce isolation, THE Platform SHALL provide one collection per workspace with a collection-scoped JWT minted by a vector-access broker.
6. WHEN a tenant holds more than 256 granted matters, THE Retrieval_Service SHALL filter by workspace and visibility only, fetch up to 500 candidates, let RLS discard disallowed ones and widen up to a cap when too few survive.
7. THE Platform SHALL treat the vector database as a sensitive store: private network, encrypted disk, scoped keys and explicit deletion of vectors on document, workspace or organization removal.
8. THE Platform SHALL keep `pgvector` as the evaluated fallback (ADR 0004) if load tests show the filtering wrapper cannot meet the budgets.

**Status:** Partial

**Evidence:** The MVP uses pgvector inside PostgreSQL under RLS (`db/migrations/0001_schema.sql`, `chunks.embedding vector(768)`; `libs/lmqa_vectorstore/src/lmqa_vectorstore/search.py`, `hybrid_candidates`), which is the design's fallback in criterion 8 (`docs/adr/0004-vector-isolation-and-pgvector.md`) (DEV-02). Criteria 1, 2 and 4 are coded for Qdrant in `libs/lmqa_vectorstore/src/lmqa_vectorstore/qdrant.py` (`build_filter`, `VectorReader`, `VectorWriter`, `INLINE_MATTERS = 256`) and `services/retrieval/src/retrieval/service.py` (`not_visible` drops), behind the disabled `qdrant_vectors` flag; import-linter forbids `qdrant_client` outside `lmqa_vectorstore` (`pyproject.toml`). Criterion 6's over-fetch path was not found beyond the constant. Criteria 3, 5 and 7 were not found.

### Requirement 36: Index consistency with PostgreSQL as authority

**ID:** R-36 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §10.6, §6.5, DEF-55 · **Gates:** G4.10, G4.11, G5.8

**User Story:** As a security reviewer, I want vector payload changes to follow PostgreSQL through an outbox and a reconciler, so that a lagging index can only hide content, never reveal it.

#### Acceptance Criteria

1. WHEN a document's visibility, matter, tier or owner changes, or the document is deleted, THE Database SHALL write an `index_outbox` row in the same transaction and mark the version's `index_state` `stale`.
2. THE Indexer SHALL apply payload updates and deletions, mark `index_state = in_sync`, retry failures with backoff and alert when the oldest pending item is older than 60 seconds.
3. WHILE a version is `stale`, THE Retrieval_Service SHALL return its content only where the Database still allows it.
4. THE Reconciler SHALL run nightly and on demand per workspace, re-upsert missing vectors, delete orphan vectors after a 24-hour grace period, correct vectors whose scope fields disagree with the Database and raise an alert for each such correction.
5. THE Ingestion_Service SHALL keep chunks immutable per document version, create a new version on re-ingest, mark searchable payloads with `is_current` and keep old versions readable by audit under legal hold.
6. WHEN a document is deleted, THE Platform SHALL destroy the document key, then delete vectors and objects through the outbox, and THE Reconciler SHALL verify that no vector remains.

**Status:** Partial

**Evidence:** Criterion 1 is coded in `db/policies/11_access.sql` (`app_outbox_trigger`, trigger `documents_outbox` on visibility, matter, tier and owner) and `index_outbox` in `db/migrations/0006_production_core.sql`; deletion is not covered by the trigger. Criteria 2, 4 and 6 are coded in `services/ingestion/src/ingestion/production.py` (`Indexer.run_once`, `Reconciler.run_workspace`, `DriftReport`, `erase_document`), behind disabled flags and untested. Criterion 3 holds in the MVP because pgvector search runs under RLS. Criterion 5: `document_versions` exists; `is_current` and `payload_version` columns were not found; MVP re-runs replace chunks (`services/ingestion/src/ingestion/pipeline.py`).

### Requirement 37: Scoped semantic answer cache

**ID:** R-37 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §10.7, §11.4 step 4, DEF-06, DEF-28, D12 · **Gates:** G6.5

**User Story:** As a security reviewer, I want cached answers keyed by scope and retrieved chunk set after retrieval runs, so that a cache hit can never reveal more than the caller could retrieve.

#### Acceptance Criteria

1. THE Generation_Service SHALL own the cache and SHALL consult it only after retrieval has run.
2. THE Generation_Service SHALL key entries by a hash of `org_id`, `workspace_id`, `scope_hash`, the retrieved chunk-set hash (IDs and versions), `prompt_version`, model identifier and normalized query, and SHALL allow near-duplicate matching only inside one such bucket.
3. WHEN a cached answer is used, THE Validator SHALL re-check it against the current ledger before release.
4. THE Generation_Service SHALL encrypt entries with the workspace cache key (rotated daily), keep them at most one hour and never share them across workspaces.
5. WHERE an organization is medical, THE Generation_Service SHALL keep caching off unless the organization opts in.

**Status:** Partial

**Evidence:** Criteria 2, 4 and 5 are coded in `services/generation/src/generation/cache.py` (`cache_key`, `chunk_set_hash`, `AnswerCache` with AES-256-GCM and the medical default off). `AnswerCache` is not referenced by any other module, so criteria 1 and 3 are not met on any request path.

### Requirement 38: Fair asynchronous ingestion without cross-workspace deduplication

**ID:** R-38 · **Type:** NFR · **Priority:** P0 · **Persona:** Admin · **Design:** §10.8 · **Gates:** G4.8, G4.9

**User Story:** As an admin, I want my uploads processed fairly and never deduplicated against other workspaces, so that a neighbor's flood cannot starve me and deduplication cannot reveal what others hold.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL give each workspace N job-lock slots (`ws:{id}:slot:{k}`, N = its concurrency cap).
2. WHILE workspace A uploads 500-page documents continuously, THE Ingestion_Service SHALL keep workspace B's ingestion p95 within twice its idle baseline.
3. THE Ingestion_Service SHALL accept uploads only through presigned PUT URLs constrained to the workspace prefix, size, content type and a required SHA-256 checksum.
4. THE Ingestion_Service SHALL scan and type-verify files before OCR or parsing.
5. THE Platform SHALL never deduplicate or cache identical files, chunks or embeddings across workspaces.

**Status:** Partial

**Evidence:** Criterion 1 is coded in `services/ingestion/src/ingestion/production.py` (`slot_lock`) and proven by `test_slot_locks_bound_each_workspace_and_share_the_worker` (`tests/integration/test_stage0_queue_spike.py`); the MVP path does not use it. Criterion 3 is coded in `libs/lmqa_objectstore/src/lmqa_objectstore/s3.py` (`presign_upload`), flag off; the MVP accepts a multipart POST through the Gateway (DEV-22). Criterion 4: magic-byte checks exist in `services/ingestion/src/ingestion/parsers.py` (`detect_type`); ClamAV is flag-gated. Criterion 5 is not met: `embedding_cache` is keyed by `(org_id, model, text_sha256)` (`db/migrations/0004_retrieval.sql`), so embeddings are shared across workspaces of one organization (DEV-04). Criterion 2 is untested.

### Requirement 39: LLM and prompt-injection controls

**ID:** R-39 · **Type:** FR · **Priority:** P0 · **Persona:** Engineer · **Design:** §10.9, §23 prompt injection · **Gates:** G6.4, G6.6

**User Story:** As a security reviewer, I want the model to receive only permitted chunks inside delimited, untrusted blocks with no tools, so that an injected instruction in a shared document cannot widen access or exfiltrate data.

#### Acceptance Criteria

1. THE Generation_Service SHALL place only chunks that passed retrieval filters into the prompt.
2. THE Generation_Service SHALL delimit chunk blocks, state an instruction hierarchy that treats chunk text as untrusted data, and use request-local aliases instead of global IDs.
3. THE Generation_Service SHALL give the generation model no tools and no network access.
4. THE Frontend SHALL sanitize model output and document content in the viewer.
5. THE Platform SHALL log prompts and completions only into the organization-scoped, sealed audit payload.

**Status:** Partial

**Evidence:** Criteria 1 and 2 are met: `services/generation/src/generation/prompts.py` (`_source_block`, aliases) and `prompts/templates/answer.md` (untrusted-content rule). Criterion 3 is met for answer calls; the Anthropic adapter uses one forced tool whose schema is the answer format, which provides no capability (`services/generation/src/generation/providers.py`). Criterion 4 is partly met: no `dangerouslySetInnerHTML` occurs anywhere in `frontend/src`, so React escapes model output; no sanitized document viewer or XSS-corpus test exists. Criterion 5 is not met: questions and results are stored in plaintext in `queries` (`db/migrations/0001_schema.sql`), and sealed payloads are flag-gated (R-60).

### Requirement 40: Pooled by default, siloed when required

**ID:** R-40 · **Type:** NFR · **Priority:** P2 · **Persona:** Super Admin · **Design:** §10.10, D5 · **Gates:** G10.8

**User Story:** As a hospital system that requires physical separation, I want my organization mapped to dedicated infrastructure through the same interface, so that the silo tier needs no code changes.

#### Acceptance Criteria

1. THE Database access library SHALL provide an `OrgRouter` that maps `org_id` to its connection set (database DSN, vector collection or cluster, bucket, KMS key).
2. THE Platform SHALL use the pooled mapping by default and a dedicated mapping for organizations on the silo tier.
3. IF a silo organization has no dedicated mapping, THEN THE `OrgRouter` SHALL refuse to fall back to pooled infrastructure.

**Status:** Partial

**Evidence:** Criteria 2 and 3 are coded for the database only in `libs/lmqa_db/src/lmqa_db/service.py` (`OrgRouter.for_org`, error on missing `PG_DSN_ORG_*`). Criterion 1 is partly met: the router covers database DSNs, not vector collections, buckets or KMS keys. `OrgRouter` is not used by any service.

### Requirement 41: Ingestion pipeline

**ID:** R-41 · **Type:** FR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §11.1 steps 1 to 10, §6.5, DEF-23, DEF-34, D32 · **Gates:** G4.1, G4.2, G4.6, G4.7, G4.12

**User Story:** As an uploader, I want my documents scanned, parsed by structure, chunked faithfully, encrypted and indexed by the ingestion service, so that what is searched is exactly what the document says.

#### Acceptance Criteria

1. WHEN an uploader calls `POST /v1/documents/uploads`, THE Ingestion_Service SHALL check quota and tier ceiling, create a `documents` row in `uploading` and return a presigned PUT to the quarantine prefix bound to workspace, size, content type and a required SHA-256 checksum, and IF a check fails, THEN THE Ingestion_Service SHALL reject with a uniform error and store nothing.
2. WHEN an uploader calls `POST /v1/documents/{id}/complete`, THE Ingestion_Service SHALL verify that the object exists and its checksum matches, set the state `scanning` and enqueue the job in the same transaction, and IF the checksum does not match, THEN THE Ingestion_Service SHALL delete the object and mark the document `failed`.
3. THE Ingestion_Service SHALL scan every file with ClamAV, verify magic bytes against the declared type, enforce size, page and decompression-bomb limits and remove PDF active content (JavaScript, embedded files, launch actions) before any parser runs, and IF a file is infected or malformed, THEN THE Ingestion_Service SHALL delete it and mark the document `failed` with a reason code.
4. THE Ingestion_Service SHALL parse structured sources first (JATS XML, SPL XML, DOCX, sanitized HTML), use a PDF's text layer where present, send pages without a usable text layer to OCR and record the extraction mode per page.
5. IF a parser crashes, THEN THE Ingestion_Service SHALL isolate the crash to a sandboxed worker process, retry once and then mark the document `failed`.
6. THE Ingestion_Service SHALL detect legal structure (ARTICLE, Section, Clause numbering, schedules, exhibits, defined terms) and medical structure (SOAP headers, HPI, medication lists, encounter boundaries, LOINC section codes, JATS section titles), and IF no structure is found, THEN THE Ingestion_Service SHALL fall back to paragraph chunks recorded as `structure = fallback` and shown as a warning.
7. THE Ingestion_Service SHALL build chunks by structural unit, including a preamble chunk for text before the first heading and table chunks that keep rows together, with token targets of minimum 40, target 300 to 700 and maximum 1,200, splitting longer units on paragraph boundaries with about 10 percent overlap recorded in metadata.
8. THE Ingestion_Service SHALL encrypt chunk text with a per-document key wrapped by the workspace key (AES-256-GCM with associated data binding organization, workspace, document, version and chunk ordinal), re-encrypt the original into the final prefix and delete the quarantine object, and IF a write fails, THEN THE Ingestion_Service SHALL leave the document `failed` with no partial chunk set searchable.
9. THE Indexer SHALL embed chunks (dense and sparse), upsert them to the vector store and mark `index_state = in_sync`, and SHALL never embed quarantined chunks.
10. WHEN indexing completes, THE Ingestion_Service SHALL mark the document `indexed` and notify the owner, and SHALL route poison jobs to a dead-letter queue with an alert.
11. THE Gateway SHALL only route ingestion requests and SHALL hold no object-store credentials and presign no URLs.
12. THE Ingestion_Service SHALL choose the parser stack by a recorded bake-off of a layout-aware parser against a `pdfplumber` plus Tesseract baseline.

**Status:** Partial

**Evidence:** Criteria 4 (PDF text layer, DOCX, HTML, JATS, SPL and eCFR XML; per-page counting), 6 (headings, numbered clauses, `fallback`) and the preamble part of 7 are met in `services/ingestion/src/ingestion/parsers.py` and `chunker.py` (`build_chunks`, `merge_small`, about 10 percent overlap per `docs/mvp.md`). All-or-nothing indexing in criterion 8 is met in `services/ingestion/src/ingestion/pipeline.py` (one transaction). Magic-byte checks in criterion 3 are in `parsers.py` (`detect_type`). Chunk sizes are character-based (`TARGET_CHARS = 1600`, `MIN_CHARS = 200`) instead of token targets, and no table chunks exist (DEV-25). Criteria 1, 2 and 11 are not met: uploads are a single multipart `POST /v1/documents` read by the Gateway process (`services/gateway/src/gateway/app.py`, `upload`) (DEV-22). ClamAV and PDF active-content removal (criterion 3) and encryption (criterion 8) are coded in `services/ingestion/src/ingestion/scan.py` and `production.py`, behind disabled flags. Criteria 5, 10 (dead-letter queue) and 12 were not found; medical structure detection beyond JATS and SPL section titles was not found.

### Requirement 42: OCR confidence, quarantine and review

**ID:** R-42 · **Type:** MLR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §11.1 step 5 and OCR review, §6.5, DEF-33 · **Gates:** G4.5

**User Story:** As a document owner, I want low-confidence OCR pages held for my review instead of silently indexed, so that answers never cite misread text.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL run Tesseract with per-word confidence and compute page confidence as the length-weighted mean of word confidences plus the share of low-confidence words.
2. THE Ingestion_Service SHALL apply a default page threshold of 0.85, configurable per organization.
3. WHEN a page falls below the threshold, THE Ingestion_Service SHALL create quarantined chunks for it, move the document to `ocr_review`, and THE Indexer SHALL not embed those chunks.
4. WHEN the owner or admin reviews a quarantined page, THE Frontend SHALL show the page image beside the extracted text and THE Ingestion_Service SHALL create a new document version with `text_source = human_corrected` and offsets preserved.
5. THE Platform SHALL expose the review queue depth as a staffed metric.

**Status:** Partial

**Evidence:** Criteria 1 to 3 are coded in `services/ingestion/src/ingestion/ocr.py` (`ocr_pdf_pages`, `DEFAULT_THRESHOLD`, `OcrPage.quarantined`; confidence is the character-weighted mean without the low-confidence share), behind the disabled `malware_scan_ocr` flag; the production worker does not call it. The MVP reports pages without a text layer and never embeds them (`docs/mvp.md`). Criterion 4: no review screen with page image was found; `text_source` allows `text_layer`, `ocr`, `mixed`, `structured` but not `human_corrected` (`db/migrations/0006_production_core.sql`). Criterion 5 was not found.

### Requirement 43: Chunk model and citation resolution

**ID:** R-43 · **Type:** DR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §11.2, DEF-40 · **Gates:** G4.2, G4.3, G7.10

**User Story:** As a lawyer or clinician, I want every citation to resolve to the document, version, page range, section or clause and highlighted span, so that I can verify the claim against the source.

#### Acceptance Criteria

1. THE Database SHALL store for each chunk: `chunk_id`, `doc_id`, `doc_version`, `ordinal`; access fields `org_id`, `workspace_id`, `owner_user_id`, `matter_id`, `visibility`, `confidentiality_tier`; compliance tags `privilege` (none, attorney-client, work product) and `contains_phi`; `kind` (preamble, clause, section, soap_subjective, soap_objective, soap_assessment, soap_plan, paragraph, table, footnote); `section_path`, `clause_no`, `heading`; `page_start`, `page_end`, `spans[]` with page, character offsets and bounding boxes; `text_ciphertext`, `text_sha256`, `token_count`, `ocr_confidence_min`, `ocr_confidence_mean`, `quarantined`, `text_source`; `effective_date`, `is_current`, `payload_version`.
2. THE Ingestion_Service SHALL never change a chunk after creation.
3. WHEN a user opens a citation, THE Platform SHALL resolve the request-local alias through the ledger to document title and version, page range, section path or clause number and highlighted span.
4. WHEN a user opens the citation side panel, THE Database SHALL re-check visibility under RLS so that a permission change after the answer still applies.
5. FOR ALL ingested chunks, THE Test_Suite SHALL verify that the normalized chunk text equals the text re-extracted from the original at the stored page and offsets (round-trip property).

**Status:** Partial

**Evidence:** Criterion 1 is partly met: `db/migrations/0001_schema.sql` and `0006_production_core.sql` store IDs, access fields, `kind` (preamble, section, paragraph), `section`, `heading_path`, `clause_label`, `page_start`, `page_end`, `char_start`, `char_end`, `text`, `text_ciphertext`, `text_sha256`, `token_count`, `ocr_confidence`, `version`; `privilege`, `contains_phi`, `spans[]` with bounding boxes, `quarantined`, `text_source` on chunks, `effective_date`, `is_current` and `payload_version` are missing. Criteria 3 and 4 are met in the MVP: citations resolve to document, pages, section and the quote span (`services/citation_validator/src/citation_validator/validator.py`, `find_quote`; `frontend/src/components/chat/citation-panel.tsx`), and `QueryFlow.with_current_citations` re-reads under RLS (`services/gateway/src/gateway/query_flow.py`). Criterion 5: no fidelity test exists.

### Requirement 44: Scoped hybrid retrieval

**ID:** R-44 · **Type:** MLR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §11.3, DEF-14 · **Gates:** G5.3, G5.11, G5.12

**User Story:** As a user asking about exact statute numbers, drug names or dosages, I want hybrid search with re-ranking inside my scope, so that relevant passages are found without crossing permissions.

#### Acceptance Criteria

1. WHEN a retrieval request arrives, THE Retrieval_Service SHALL verify the Context_Token, open a transaction with context, resolve the scope from the Database (allowed matters with tier ceilings, walls, active exceptions and sessions, workspace flags) and cache it under `scope_hash` and `scope_version` for at most 30 seconds, invalidated on any change.
2. THE Retrieval_Service SHALL run one hybrid query with dense and sparse prefetch of 100 candidates each, fused by reciprocal rank fusion.
3. THE Retrieval_Service SHALL fetch the candidates' chunk text from the Database under RLS and decrypt it, dropping and counting any ID that does not come back.
4. THE Retrieval_Service SHALL re-rank surviving candidates with a cross-encoder and keep at most 12 chunks at or above the calibrated relevance threshold, recording the rest as dropped with their score.
5. THE Retrieval_Service SHALL write the retrieval record in the same transaction and return `request_id` and counts to the Gateway.
6. THE Eval_Harness SHALL measure Recall@k, MRR and nDCG on the real evaluation sets against `eval/floors.toml`, and SHALL show that hybrid search beats dense-only and sparse-only search in an ablation.
7. THE Platform SHALL use the default parameters prefetch 100 + 100, keep 12, context budget 12,000 tokens and maximum output 1,500 tokens until the Eval_Harness tunes them, and SHALL lower an evaluation floor only through an ADR.

**Status:** Partial

**Evidence:** Criteria 2 to 4 are met in the MVP: `services/retrieval/src/retrieval/service.py` (dense, stemmed full-text and exact-identifier channels fused by weighted RRF with 100 candidates per channel; `not_visible` drops under RLS; cross-encoder `BAAI/bge-reranker-v2-m3` with `rerank_min_score`; `retrieval_top_k = 12`) and `services/retrieval/src/retrieval/rerank.py`. Criterion 6 is partly met: `eval/harness/run.py` reports recall@k, MRR, nDCG and abstention for three configurations; `eval/floors.toml` floors recall, MRR and abstention on labels marked as needing human review. Criterion 7 is partly met: `context_budget_tokens = 12000`, but `llm_max_output_tokens = 8192` (`libs/lmqa_models/src/lmqa_models/settings.py`) (DEV-31). Criterion 1: no Context_Token and no scope cache; the MVP adds LLM query planning and query expansion before retrieval, which the design does not specify (DEV-21). Criterion 5: the ledger is written by the Gateway's query-flow transaction (R-31).

### Requirement 45: Token budget and optimization

**ID:** R-45 · **Type:** MLR · **Priority:** P0 · **Persona:** Engineer · **Design:** §11.4, §2.1 goal 3 · **Gates:** G6.1, G6.2, G6.3

**User Story:** As an operator of LLM spend, I want a hard per-request token budget enforced before any LLM call, so that 50 to 200+ page documents fit without truncating evidence.

#### Acceptance Criteria

1. THE Generation_Service SHALL count prompt tokens before sending using the provider's own tokenizer or token-count endpoint, agreeing with the provider's reported usage within 1 percent.
2. FOR ALL chunk sets, including adversarial chunk sizes, THE Generation_Service SHALL produce a prompt that never exceeds the budget (invariant).
3. THE Generation_Service SHALL drop chunks below the relevance threshold whole and never cut a chunk.
4. WHERE compression is applied, THE Generation_Service SHALL compress only verbose prose chunks, never tables, and IF a compression drops any critical token (number, date, currency amount, dosage with unit, statute or section reference, defined term), THEN THE Generation_Service SHALL discard the compression and use or drop the uncompressed chunk.
5. THE Validator SHALL check against the original chunk text, never the compressed text.
6. THE Generation_Service SHALL place the most relevant chunks at the start and end of the prompt.
7. THE Generation_Service SHALL record tokens in and out and every chunk dropped by the trim step with its reason.

**Status:** Partial

**Evidence:** Criteria 3, 6 and 7 are met: `services/retrieval/src/retrieval/service.py` admits whole passages with `token_budget` drop reasons; `services/generation/src/generation/prompts.py` (`reorder`); `queries.tokens_in` and `tokens_out` (`db/migrations/0001_schema.sql`). Criterion 2 is met in code by `budget_prompt` (`services/generation/src/generation/streaming.py`) and `GenerationService.draft`, without a property test. Criterion 1 is not met: tokens are estimated (`estimate_tokens` in `prompts.py` and `chunker.py`) (DEV-32). Criteria 4 and 5 are not applicable until compression exists; no compression was found.

### Requirement 46: Prompt and citation protocol

**ID:** R-46 · **Type:** MLR · **Priority:** P0 · **Persona:** Engineer · **Design:** §11.5, DEF-35 · **Gates:** G6.4, G6.7, G6.9

**User Story:** As a validator owner, I want a fixed, versioned prompt protocol in which the model tags sentences and never writes the citation list, so that citations can be checked mechanically.

#### Acceptance Criteria

1. THE Generation_Service SHALL load versioned system prompts from `prompts/templates/` that fix the output format, require every factual sentence to end with one or more `[chunk_N]` tags, define the canonical refusal "The provided documents do not address this." and declare text inside chunk blocks as untrusted data.
2. THE Generation_Service SHALL inject chunks as `<chunk alias="chunk_3" doc="…" page="12-13" section="4.2">…</chunk>` with aliases mapped to chunk IDs only through the ledger.
3. THE Validator SHALL build the citation list deterministically from the tags of validated sentences, and THE Generation_Service SHALL not ask the model for a citation list.
4. THE Generation_Service SHALL include few-shot examples in `prompts/few_shot_examples/` for single-chunk and multi-chunk citations and at least one correct refusal.
5. THE Generation_Service SHALL hash every prompt version and THE Audit_Service SHALL record the hash, model identifier and provider settings in every query's audit payload.

**Status:** Partial

**Evidence:** Criteria 4 and 5 (hash and model) are met: `prompts/few_shot_examples/answer.md`, `prompts/registry.toml`, `services/generation/src/generation/prompts.py` (`load_prompts` with SHA-256), `queries.prompt_sha256` and `model` (`db/migrations/0001_schema.sql`). Criterion 1 is partly met: templates, the canonical refusal and the untrusted-content rule exist in `prompts/templates/answer.md` and `answer_stream.md`, but tags are `[S1]` (DEV-07). Criterion 3 is partly met: the MVP builds the citation list from validated sentences, but the buffered answer schema asks the model for per-citation quotes (`services/citation_validator/src/citation_validator/validator.py`, check Q) (DEV-06). Criterion 2 uses a different block format (`_source_block`).

### Requirement 47: Deterministic citation validator

**ID:** R-47 · **Type:** FR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §11.6 validator checks, §2.1 goals 1 and 2, DEF-15, DEF-51 · **Gates:** G7.1 to G7.6, G7.10

**User Story:** As a user relying on an answer, I want every sentence checked by deterministic rules against the exact chunks retrieved for my request, so that unsupported claims are removed before I see them.

#### Acceptance Criteria

1. THE Validator SHALL fail a sentence whose tags do not match `[chunk_N]` exactly (V1).
2. THE Validator SHALL fail a sentence citing an alias that is not in this request's ledger (V2).
3. THE Validator SHALL fail a sentence whose cited chunk's current content hash differs from the ledger hash (V3).
4. THE Validator SHALL fail an uncited factual sentence; headings and the canonical refusal are exempt (V4).
5. THE Validator SHALL fail a sentence containing a number, date, amount, dosage with unit or statute or section reference that does not appear in the cited chunk text after normalization of units, thousands separators and date formats (V5).
6. THE Validator SHALL score each sentence against the cited chunks' relevant windows with a pinned NLI cross-encoder and fail it below the calibrated threshold, concatenating windows for multi-chunk sentences (V6).
7. THE Validator SHALL accept a refusal only in the exact canonical wording with no tags and no other claim in the sentence, allow a partial answer followed by a refusal, and replace the whole answer with the canonical refusal when every content sentence fails (V7).
8. THE Validator SHALL fail a tag that does not resolve to document, page range, section and highlighted span (V8).
9. THE Validator SHALL return the same verdict for the same input on every run and after every restart, with the NLI model pinned by weights hash, CPU inference, fixed batch size and fixed thresholds.
10. THE Validator SHALL call no generative LLM.
11. THE Eval_Harness SHALL calibrate the NLI threshold on at least 300 human-labeled sentence–chunk pairs per domain so that precision of "supported" is at least 0.99 on a held-out set, with the floor in `eval/floors.toml`.
12. THE Validator SHALL own sentence segmentation with one pinned segmenter.

**Status:** Partial

**Evidence:** Criteria 2, 3, 4, 5, 7 (partly) and 8 are met in `services/citation_validator/src/citation_validator/validator.py` (`validate`, `recheck_integrity`, `numbers`, `find_quote`) and re-checked at release in `services/gateway/src/gateway/query_flow.py`. Criterion 1 is met for the MVP grammar `S<n>`, not `[chunk_N]` (DEV-07). Criterion 7 adds a "scoped refusal" form not in the design (DEV-06). Criterion 12 is coded in `services/citation_validator/src/citation_validator/streaming.py` (`SentenceSegmenter`), flag off. Criteria 6 and 9 are coded in `services/citation_validator/src/citation_validator/nli.py` (`NliModel` with `NLI_MODEL_HASH`, single-thread ONNX), behind the disabled `pinned_nli_validator` flag; the MVP runs an LLM entailment pass (`GenerationService.entailment`), which breaks criteria 9 and 10 (DEV-05). Criterion 11: no labeled calibration set exists. The MVP adds checks Q and L not in the design (DEV-06).

### Requirement 48: Gated delivery, signed verdicts, write-ahead audit and stream protocol

**ID:** R-48 · **Type:** FR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §3.1 principle 12, §4.4, §11.6 delivery modes, outcomes, signed verdicts and stream protocol, DEF-05, DEF-38, DEF-50, DEF-62, D15 · **Gates:** G7.6 to G7.12

**User Story:** As a user, I want to see each sentence only after it has been validated and audited, so that no unverified text ever reaches me and what I saw is provably what was validated.

#### Acceptance Criteria

1. WHERE the organization policy is `sentence_gated` (default, with `on_fail = strip`), THE Gateway SHALL forward the generation stream to the Validator and release only sentences carrying a passing Verdict.
2. WHERE the organization policy is `on_fail = regenerate`, THE Gateway SHALL use `buffered` mode, release nothing until the whole answer validates, regenerate at most 2 times and then fail the query with a clear message.
3. THE Platform SHALL provide no delivery mode that shows unverified text.
4. WHEN a sentence fails under `strip`, THE Gateway SHALL release the visible marker "A claim in this answer could not be verified and was removed" with a reason code, and WHEN no verified answer can be produced, THE Gateway SHALL release a final refusal.
5. THE Validator SHALL sign each Verdict with its KMS-certified ephemeral key over (`request_id`, sentence SHA-256, verdict, check results) and carry the sentence text in the Verdict.
6. THE Gateway SHALL release a sentence only when it holds a Verdict signed by the Validator for that sentence and request.
7. WHEN a query starts, THE Gateway SHALL commit `query.started` before retrieval; before each sentence leaves the system THE Gateway SHALL commit a `segment.released` audit event with hashes only; at the end THE Gateway SHALL commit `query.completed` with the sealed payload (question, chunk references, full answer, verdicts, prompt hash, tokens, dropped chunks), the hash of the released text and the verdict signatures.
8. IF any audit write fails, THEN THE Gateway SHALL stop the stream with an error and release nothing after the failure.
9. THE Gateway SHALL stream SSE events `status` (retrieving, generating, validating), `sentence` (text, citation aliases, event ID), `citations`, `warning`, `done` and `error`.
10. THE Gateway SHALL keep released sentences for 10 minutes in an encrypted, workspace-scoped Valkey resume buffer keyed by `request_id`, and WHEN a client reconnects with `Last-Event-ID`, THE Gateway SHALL send only sentences from that buffer.
11. THE Gateway SHALL orchestrate the fan-out so that services never call each other and never forward user context.
12. THE Platform SHALL log every Verdict.

**Status:** Partial

**Evidence:** The MVP meets criteria 3, 4 (strip marker and refusal) and a buffered form of 8: `services/gateway/src/gateway/query_flow.py` validates the whole answer, commits query, ledger and audit event in one transaction, then returns; failing sentences become a visible marker (`docs/mvp.md`). Criteria 1, 5, 6, 7, 8, 9 and 10 are coded in `services/gateway/src/gateway/stream.py` (`SentenceStream` with `meta`, `sentence`, `stripped`, `done`, `error` events, write-ahead `segment.released`, resume) and `services/citation_validator/src/citation_validator/streaming.py` (`sign_verdict`, `verify_verdict`), behind the disabled `sentence_streaming` flag. The stream events differ from the design (`meta` and `stripped` instead of `status`, `citations`, `warning`), and the resume buffer is the `query_segments` table (`db/migrations/0008_streaming_release.sql`), not Valkey. Criterion 2 (`regenerate`) was not found; `workspaces.on_fail` exists as a column only. Criterion 11 holds in the single process trivially (DEV-01).

### Requirement 49: Prompt and model lifecycle

**ID:** R-49 · **Type:** MLR · **Priority:** P1 · **Persona:** Engineer · **Design:** §11.7 · **Gates:** G6.9, G11.7

**User Story:** As a model owner, I want prompt and model changes promoted only when evaluation floors hold and rolled out by canary, so that quality never regresses silently.

#### Acceptance Criteria

1. THE Generation_Service SHALL version every template in `prompts/` by content hash with the repository as source of truth.
2. IF the Eval_Harness shows citation-validation pass rate, refusal accuracy or retrieval metrics below `eval/floors.toml`, THEN THE Toolchain SHALL block promotion of the prompt or model change.
3. WHEN a prompt or model change is deployed, THE Platform SHALL run it as a canary evaluated against the live validation pass rate and roll it back on a drop.
4. WHERE self-hosted Langfuse is used for traces and A/B analysis, THE Platform SHALL keep the repository as the source of truth.

**Status:** Partial

**Evidence:** Criterion 1 is met: `prompts/registry.toml` and `services/generation/src/generation/prompts.py`. Criterion 2 is partly met: `make eval` fails below floors (`eval/harness/run.py`), but no promotion gate is wired. Criteria 3 and 4 were not found.

### Requirement 50: LLM and embedding provider boundary

**ID:** R-50 · **Type:** IR · **Priority:** P0 · **Persona:** Super Admin · **Design:** §11.8, §10.5 vectors and sparse terms, D17 · **Gates:** G6.8

**User Story:** As an organization owner, I want my LLM and embedding providers, keys and budgets chosen per organization under no-retention or BAA terms, so that my documents cross only the boundary I agreed to.

#### Acceptance Criteria

1. THE Generation_Service SHALL select the LLM provider, key and budget per organization.
2. WHERE an organization is medical, THE Generation_Service SHALL default to a provider under a BAA with no-retention terms, or a VPC-isolated or self-hosted model; WHERE it is legal, THE Generation_Service SHALL default to a no-retention contract.
3. THE Generation_Service SHALL expose a provider-agnostic `llm_client` that supports streaming, timeouts, idempotent retries and per-organization keys and budgets.
4. THE Ingestion_Service SHALL treat the embedding provider as a data boundary with the same no-retention terms as the LLM and SHALL use a self-hosted embedding model for sensitive organizations.
5. THE Platform SHALL build and test a self-hosted model option by Stage 11 and record the choice per organization.

**Status:** Partial

**Evidence:** Criterion 3 is partly met: `services/generation/src/generation/llm_client.py` and `providers.py` (Gemini, OpenAI-compatible, Anthropic; timeouts and fallback chain) and `streaming.py` (streaming with cancellation). Criteria 1, 2 and 4 are not met: the provider, keys and fallback chain are global environment settings (`LLM_PROVIDER`, `LLM_FALLBACK_MODELS`), and embeddings always use Gemini (`libs/lmqa_vectorstore/src/lmqa_vectorstore/embeddings.py`) (DEV-03, DEV-31). Criterion 5: a local re-ranker exists; the `self_hosted_models` flag is off.

### Requirement 51: Key hierarchy and field encryption

**ID:** R-51 · **Type:** DR · **Priority:** P0 · **Persona:** Super Admin · **Design:** §3.1 principle 9, §12.1, §12.2, DEF-03 · **Gates:** G1.10

**User Story:** As a customer, I want my content encrypted under independent keys per organization, workspace and document, so that each level can be destroyed on its own and copied ciphertext is useless.

#### Acceptance Criteria

1. THE Key_Ring SHALL hold one KMS symmetric CMK per organization (multi-Region primary plus replica) used only to wrap the keys below.
2. THE Key_Ring SHALL use independent random 256-bit keys for each workspace content key (versioned, wrapped by the CMK), document key (wrapped by the workspace key), organization control key, daily cache key and blind-index key, plus an X25519 audit key pair per workspace per calendar month with the private key wrapped by the CMK.
3. THE Platform SHALL encrypt document titles, chunk text, questions, answers, audit payloads, user contact fields and reason text with AES-256-GCM and associated data binding `org_id`, `workspace_id`, object ID and version.
4. IF a ciphertext is copied into another row or workspace, THEN decryption SHALL fail.
5. THE Platform SHALL perform equality lookups on email and code lookup ID through HMAC blind indexes.
6. THE Platform SHALL hold the code pepper in the secret manager, versioned, and the context-token trust root as a KMS ECC P-256 sign-and-verify key rotated every 90 days with overlap.

**Status:** Partial

**Evidence:** Criteria 1, 2 and 4 are coded in `libs/lmqa_keys/src/lmqa_keys/keyring.py` (`KeyRing`, `DekCache`), `envelope.py` (`Binding`, `encrypt_value`, `wrap_key`), `providers.py` (`AwsKmsProvider.replicate`) and tables `org_keys`, `workspace_keys`, `doc_keys`, `audit_keys` (`db/migrations/0006_production_core.sql`), behind the disabled `envelope_encryption` flag. Audit keys are per organization per month, not per workspace (DEV-18). Criterion 5 has columns `users.email_blind_index` and `email_ciphertext`. Criterion 3 is not met in the MVP: chunk text, titles, questions and emails are plaintext columns (`db/migrations/0001_schema.sql`) (DEV-09). The trust root exists as `aws_kms_key.trust_root` in `infra/aws/main.tf`; the pepper is a settings value.

### Requirement 52: Object encryption

**ID:** R-52 · **Type:** DR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §12.3 · **Gates:** G4.1, G4.11

**User Story:** As a customer, I want stored originals encrypted by the application identically in every environment, so that the object store never holds plaintext.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL land uploads in a quarantine prefix (SSE-KMS and 24-hour lifecycle expiry in production).
2. WHEN scanning and parsing finish, THE Ingestion_Service SHALL stream the file through chunked AES-GCM (1 MiB segments, per-segment nonces, final-segment marker) under the document key into the final prefix and delete the quarantine object.
3. WHEN a user downloads a document, THE Ingestion_Service SHALL decrypt and stream it through the Gateway, and THE Platform SHALL never give the browser a URL to ciphertext; presigned URLs SHALL exist only for uploads to the quarantine prefix.
4. FOR ALL objects, decrypting an encrypted stream SHALL return the original bytes, and reordering, truncating or extending segments SHALL fail decryption (round-trip and integrity property).

**Status:** Partial

**Evidence:** Criteria 1, 2 and 4 are coded in `libs/lmqa_objectstore/src/lmqa_objectstore/s3.py` (`S3ObjectStore.presign_upload`, `put_encrypted`, `get_decrypted`, `delete_quarantine`) and `libs/lmqa_keys/src/lmqa_keys/envelope.py` (`encrypt_stream`, `decrypt_stream` with a last-segment flag), behind the disabled `object_store` flag. The MVP stores originals unencrypted under `data/objects` (`libs/lmqa_objectstore/src/lmqa_objectstore/__init__.py`) (DEV-09, DEV-22). Criterion 3: no download endpoint exists.

### Requirement 53: Key rotation

**ID:** R-53 · **Type:** NFR · **Priority:** P1 · **Persona:** Engineer · **Design:** §12.4 · **Gates:** G1.10

**User Story:** As a key administrator, I want routine and emergency rotation that never rewrites data unnecessarily, so that compromise response is fast and routine rotation is free.

#### Acceptance Criteria

1. THE Key_Ring SHALL rely on provider automatic rotation of CMK key material with no data rewrite.
2. WHEN a workspace content key is rotated, THE Key_Ring SHALL use the new version for new documents, keep old versions readable and re-wrap document keys lazily without changing document keys.
3. THE Platform SHALL provide an emergency rotation runbook that re-wraps a workspace's document keys under a fresh workspace key and, if the CMK is suspected compromised, creates a new CMK and re-wraps every key row of the organization.
4. THE Platform SHALL rotate the trust root every 90 days with overlapping certificates trusted by services during the overlap.

**Status:** Partial

**Evidence:** Key version fields exist (`key_version` in `libs/lmqa_keys/src/lmqa_keys/envelope.py` blobs; `workspace_keys` versioned in `db/migrations/0006_production_core.sql`). No rotation or re-wrap function was found in `libs/lmqa_keys`, and no rotation runbook exists in `docs/runbooks/`. CMK automatic rotation was not verified in `infra/aws/main.tf`.

### Requirement 54: Key deletion guardrails and KeyGuard

**ID:** R-54 · **Type:** NFR · **Priority:** P0 · **Persona:** Platform operator (key custodian) · **Design:** §3.1 principle 11, §12.5, DEF-18 · **Gates:** G1.11, G1.12, G9.12

**User Story:** As a customer, I want destroying my organization's key to be hard and restoring it easy, so that one accidental or malicious act cannot make my data permanently unreadable.

#### Acceptance Criteria

1. THE Platform SHALL deny `kms:ScheduleKeyDeletion`, `kms:DisableKey`, `kms:PutKeyPolicy` and `kms:DeleteImportedKeyMaterial` through an organization-wide service control policy and key policies to every principal except `keyguard-destroyer` and `key-admin` (MFA and change ticket).
2. THE Platform SHALL let only the KeyGuard workflow assume `keyguard-destroyer`, with session tags carrying two distinct approval IDs that the key policy checks, and SHALL give service roles only `Encrypt`, `Decrypt`, `GenerateDataKey` and `ReEncrypt` with encryption-context conditions.
3. THE Platform SHALL use the provider's maximum waiting period (30 days for AWS KMS) for every non-drill key, and THE Toolchain SHALL fail a policy lint if any production key has a shorter window.
4. THE KeyGuard SHALL refuse any destroy operation unless the organization is `sealed`, an `executable` governance request has the required distinct approvers, the waiting window has elapsed, retention has ended and no legal hold exists, and THE Database SHALL keep `org_keys.deletion_protection` true otherwise.
5. WHEN a `ScheduleKeyDeletion`, `DisableKey`, `CancelKeyDeletion`, `PutKeyPolicy` or key-material event occurs, THE Platform SHALL page security within 60 seconds, and IF no approved KeyGuard record matches, THEN an automated responder whose role can only cancel and enable SHALL cancel the deletion and re-enable the key.
6. THE Platform SHALL let one person or the responder cancel a scheduled deletion and re-enable a key.

**Status:** Partial

**Evidence:** Criteria 1 to 6 are coded: `infra/keyguard/scp-deny-key-destruction.json`, `infra/keyguard/key-policy.json.tftpl`, `infra/aws/main.tf` (`keyguard_destroyer`, `keyguard_workflow`, `keyguard_responder` roles, `aws_cloudwatch_event_rule.kms_events`, `aws_lambda_function.responder`), `infra/keyguard/responder.py`, `libs/lmqa_keys/src/lmqa_keys/keyguard.py` (`authorize_destruction`, `schedule_destruction`, `respond`, `lint_key_policy`) and `org_keys.deletion_protection`. Status is Partial because nothing has been applied to an AWS account or tested (`docs/production.md` lists the AWS dev account as an external prerequisite), and the paging target is an on-call webhook not yet provided.

### Requirement 55: Two-person approval, waiting windows and sealing

**ID:** R-55 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin, key custodian · **Design:** §12.6, §6.7, DEF-56 · **Gates:** G2.10, G9.6

**User Story:** As a customer, I want unsealing, destroying and deleting to require distinct humans, step-up and long waits, and sealing to make content unreadable by key setup, so that no single person can destroy or reopen my data.

#### Acceptance Criteria

1. THE Identity_Service SHALL require, with passkey step-up within 5 minutes of each approval by distinct humans: for unsealing a workspace, the Super Admin or co-owner plus an operator `key_custodian` and a 72-hour wait; for destroying a workspace's keys, the same approvers, ended retention, no legal hold and a 30-day wait; for deleting an organization, the co-owner or an out-of-band verified signatory plus a `key_custodian` at the key stage, with a 30-day grace plus the provider window (at least 60 days in total); for platform-initiated destruction, a verified customer signatory, a `security_officer` and two `key_custodian` operators.
2. THE Identity_Service SHALL expire approvals after 72 hours and SHALL reject an approver who is the initiator.
3. THE Key_Ring SHALL keep an escrow copy of every workspace content key wrapped under the organization's escrow CMK in the vault account, whose key policy requires two custodian principals.
4. WHEN a workspace becomes `sealed`, THE Key_Ring SHALL remove the CMK-wrapped copy from the Database so that services cannot unwrap the key, and WHEN it is unsealed, THE Key_Ring SHALL re-wrap the escrow copy under the organization CMK after two custodians release it.

**Status:** Partial

**Evidence:** Criteria 1 and 2 are coded in `services/identity/src/identity/governance.py` (`KindRule`, distinct approvers and authenticators, `approval_expiry`), `libs/lmqa_models/src/lmqa_models/policy.py` (waits) and `services/identity/src/identity/destruction.py` (`workspace_destroy_effect_factory`, `workspace_unseal_effect_factory`). Criteria 3 and 4 are coded in `libs/lmqa_keys/src/lmqa_keys/keyring.py` (`seal_workspace`, `unseal_workspace`, escrow). No escrow CMK or vault account exists in `infra/aws/main.tf`. Everything is behind the disabled `governance_requests` and `envelope_encryption` flags and untested.

### Requirement 56: Organization destruction ritual

**ID:** R-56 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin, operators · **Design:** §12.7, §6.4 · **Gates:** G9.6

**User Story:** As a departing customer, I want organization deletion to run a fixed, reversible-until-the-end ritual with verification, so that deletion is deliberate, complete and provable.

#### Acceptance Criteria

1. WHEN the Super Admin starts `org_delete` with passkey step-up, no legal hold and a retention check, THE Identity_Service SHALL require a second approver (co-owner or verified signatory) before the organization enters `deletion_pending`.
2. WHILE an organization is `deletion_pending` (30 days), THE Platform SHALL keep the export window open, freeze its workspaces, notify all admins and let one person cancel.
3. WHEN the grace ends, THE Platform SHALL seal the organization, disable content keys and, after a custodian approves the key stage, delete the replica first and then schedule the CMK and the escrow key together with a 30-day window.
4. WHILE an organization is sealed, THE Platform SHALL allow restore by one person plus the custodian's cancel action, returning the organization to `frozen`.
5. WHEN the provider windows end, THE Platform SHALL delete the CMK and escrow key, vectors, objects and the Auth0 Organization, write a destruction record signed by the custodian and the security officer and add a tombstone ledger entry.
6. WHEN destruction completes, THE Test_Suite SHALL verify that decryption fails, no vector or object remains and a restore replays the tombstone.
7. WHERE a drill organization's keys carry the `drill` tag, THE Platform SHALL allow the provider's 7-day minimum window so the full path runs annually.

**Status:** Partial

**Evidence:** Criteria 1 to 5 and 7 are coded in `services/identity/src/identity/destruction.py` (`org_delete_effect`, `Lifecycle.tick`, `schedule_key_stage`, `restore`), `libs/lmqa_keys/src/lmqa_keys/keyguard.py` (drill window) and `infra/aws/org_key.tf` (`aws_kms_key.drill_org`). The signed destruction record and criterion 6 were not found. Flags off; untested.

### Requirement 57: Backup, disaster recovery and escrow

**ID:** R-57 · **Type:** NFR · **Priority:** P2 · **Persona:** Platform operator · **Design:** §12.8, §22 disaster recovery · **Gates:** G9.10, G9.12, G11.6

**User Story:** As a customer, I want my data recoverable after regional failure or malicious key deletion, and drills that prove it, so that availability does not depend on one account or one region.

#### Acceptance Criteria

1. THE Platform SHALL create each organization CMK as a multi-Region primary with a replica in the DR Region.
2. THE Key_Ring SHALL write wrapped copies of workspace, control and audit keys under a per-organization escrow CMK in a separate vault account with separate administrators and no day-to-day access.
3. THE Platform SHALL back up PostgreSQL with point-in-time recovery, Qdrant with snapshots, objects with versioning and audit anchors in an Object Lock bucket, all copied cross-Region and containing only ciphertext and wrapped keys.
4. THE Platform SHALL meet RPO ≤ 5 minutes and RTO ≤ 4 hours for the data plane.
5. THE Platform SHALL run a quarterly restore from escrow into an isolated account, an annual full destroy drill and an annual restore-and-shred drill.
6. WHERE an organization brings its own key, THE Platform SHALL state in the contract that loss of that key is loss of data.

**Status:** Partial

**Evidence:** Criterion 1 has code (`AwsKmsProvider.replicate` in `libs/lmqa_keys/src/lmqa_keys/providers.py`; saga step `kms_key`). Criterion 2 is partly coded (escrow in `keyring.py`), with no vault account in `infra/aws/main.tf`. `docs/runbooks/restore-and-shred.md` exists (6 lines). No backup configuration, PITR, snapshot or drill automation was found.

### Requirement 58: Shredding semantics and the tombstone ledger

**ID:** R-58 · **Type:** NFR · **Priority:** P1 · **Persona:** Customer, auditor · **Design:** §12.9, DEF-04 · **Gates:** G1.11, G4.11, G9.5

**User Story:** As a customer who deleted a document, I want it to stay deleted even after a backup restore, so that crypto-shredding is provable at every scope.

#### Acceptance Criteria

1. WHEN a document is deleted, THE Key_Ring SHALL destroy its document key so that chunk text and object are unrecoverable at once, and THE Indexer SHALL delete vectors and objects through the outbox.
2. WHEN a workspace is destroyed, THE Key_Ring SHALL destroy the workspace content key, all document keys and, at the end of their retention, the audit keys.
3. WHEN an organization is destroyed, THE Key_Ring SHALL destroy the CMK and escrow keys so that every wrapped key in every backup is unreadable.
4. THE Platform SHALL record every document, workspace and tenant deletion in a tombstone ledger outside the backup set (an Object Lock bucket in the vault account).
5. WHEN any restore runs, THE Platform SHALL replay the tombstone ledger before the restored system accepts traffic, restore per organization and expire backups within 35 days.

**Status:** Partial

**Evidence:** Criteria 1, 4 and 5 are coded: `KeyRing.shred_document` (`libs/lmqa_keys/src/lmqa_keys/keyring.py`), `erase_document` (`services/ingestion/src/ingestion/production.py`), `deletion_tombstones` (`db/migrations/0006_production_core.sql`), `mirror_tombstones` and `replay_tombstones` (`services/audit/src/audit/anchor.py`), `aws_s3_bucket.tombstones` with Object Lock (`infra/aws/main.tf`, not in a vault account). Criteria 2 and 3 are coded in `services/identity/src/identity/destruction.py`. The MVP deletes rows and the local file without key destruction (`services/ingestion/src/ingestion/documents.py`, `delete`). Untested.

### Requirement 59: Local key mode and repository secret hygiene

**ID:** R-59 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §12.10, DEF-10 · **Gates:** G0.6, G1.11

**User Story:** As an engineer, I want real key providers locally and secrets kept out of the repository from the first commit, so that shredding is testable and nothing secret is ever committed.

#### Acceptance Criteria

1. THE Key_Ring SHALL offer two real adapters behind one provider interface, AWS KMS (dev account) and OpenBao Transit, and SHALL use no file-backed fake.
2. THE Platform SHALL ignore `.env`, `.env.*`, `.secrets/`, `*.pem` and `*.key` in `.gitignore` with an explicit `!.env.example`.
3. THE Toolchain SHALL run gitleaks as a pre-commit hook and as a CI check.
4. THE Platform SHALL keep peppers and signing keys out of `compose.yaml`.

**Status:** Implemented

**Evidence:** Criterion 1: `libs/lmqa_keys/src/lmqa_keys/providers.py` (`AwsKmsProvider`, `OpenBaoProvider`, `provider_from_settings`); the OpenBao round trip and destruction passed in `tests/integration/test_stage0_infra.py::test_openbao_transit_round_trip_and_destruction`. Criterion 2: `.gitignore` (`.env`, `.env.*`, `!.env.example`, `.secrets`, `.secrets.*`, `*.pem`, `*.key`). Criterion 3: `.githooks/pre-commit`, `.pre-commit-config.yaml` and `.github/workflows/secret-scan.yml`. Criterion 4: `compose.yaml` takes secrets from environment variables only. **Verification:** the G0.6 tests in `tests/contract/test_stage0_toolchain.py` exist; their last run had 2 failures that were fixed without a re-run (`docs/production.md`). The context-token trust root defaults to an in-process key (R-28), which is outside this requirement.

### Requirement 60: Audit event model and sealed payloads

**ID:** R-60 · **Type:** DR · **Priority:** P0 · **Persona:** Super Admin, Admin, auditor · **Design:** §3.1 principle 7, §13.1, §13.2, DEF-27, D31 · **Gates:** G9.2

**User Story:** As an auditor, I want every action recorded as metadata plus a payload sealed so that writers cannot read it, so that owners and operators can review events without ever reading content.

#### Acceptance Criteria

1. WHEN any action occurs, THE Platform SHALL write an `audit_event` with ID, timestamp, `org_id`, `workspace_id`, actor, actor role, action, target IDs only, outcome, reason code, request ID, IP, user agent, scope, `prev_hash` and `hash`.
2. WHERE an action has content, THE Platform SHALL write an `audit_payload` (question text, retrieved chunk references, answer, verdicts, dropped chunks, token counts, prompt hash) sealed with HPKE (RFC 9180) to the workspace-month audit public key.
3. THE Platform SHALL give writers only the public key, and THE Audit_Service SHALL be the only component that unwraps the month's private key to serve reads.
4. THE Database SHALL include the hash of the payload ciphertext in the chain so that shredding a month's key does not break verification.
5. THE Platform SHALL keep sensitive text out of audit metadata and logs.

**Status:** Partial

**Evidence:** Criterion 1 is partly met: `audit_events` with organization, workspace, actor, action, target, payload, `prev_hash`, `hash` (`db/migrations/0001_schema.sql`); reason, request ID, IP and user agent are not in the MVP writer (`libs/lmqa_audit/src/lmqa_audit/__init__.py`, `append`). Criterion 5 is met for audit metadata: MVP payloads carry hashes and counts only (`services/audit/src/audit/service.py` docstring), but the question text sits in plaintext in `queries`. Criteria 2 to 4 are coded in `libs/lmqa_security/src/lmqa_security/sealing.py` (HPKE X25519, HKDF-SHA256, AES-256-GCM), `libs/lmqa_audit/src/lmqa_audit/sealed.py` (`append_sealed`), `db/policies/31_audit_sealed.sql` (`audit_append_sealed`, `audit_event_hash`) and `services/audit/src/audit/anchor.py` (`PayloadReader`), with keys per organization per month rather than per workspace (DEV-18); flag off, untested.

### Requirement 61: Audit chains, anchoring, immutability and retention

**ID:** R-61 · **Type:** NFR · **Priority:** P0 · **Persona:** Auditor · **Design:** §13.3, §13.8, DEF-16, DEF-43, DEF-45, D10 · **Gates:** G1.8, G9.1, G9.5

**User Story:** As an auditor, I want tamper-evident, externally anchored audit chains that survive retention, so that history cannot be edited even by a database superuser.

#### Acceptance Criteria

1. THE Database SHALL keep one hash chain per workspace and one control-plane chain per organization, computing `hash = H(prev_hash + canonical event)` in `audit_append` under a per-chain transaction-level advisory lock.
2. WHERE Stage 10 shows the lock limits throughput, THE Database SHALL split a workspace chain into N shards by user hash with a Merkle root covering all shard heads.
3. THE Audit_Service SHALL write an hourly Merkle root over all chain heads to an Object Lock bucket in compliance mode and verify it with a scheduled job.
4. THE Database SHALL give services no direct write access to audit tables, reject UPDATE and DELETE by trigger and partition audit tables by month.
5. WHEN a partition is detached for retention, THE Database SHALL first write and anchor a checkpoint record with the range's last hash, and THE Audit_Service SHALL treat a checkpoint as a valid chain start.
6. THE Platform SHALL apply a per-organization retention schedule with a legal-hold flag that blocks deletion, crypto-shred payloads and document content at the end of retention, keep the metadata chain verifiable and record deletions in the tombstone ledger.
7. THE Platform SHALL confirm audit-log and document retention defaults per jurisdiction with counsel, with a six-year baseline for medical documentation.

**Status:** Partial

**Evidence:** Criterion 4 is partly met: triggers `audit_no_update` and `audit_no_truncate` (`db/policies/30_audit.sql`), writes through `audit_append` only (`db/roles/grants.sql`); tables are not partitioned. Criterion 1 is partly met: `audit_append` hashes with a transaction-level advisory lock, but per organization, not per workspace (DEV-18); `audit_verify` detects tampering (`db/policies/30_audit.sql`, `make demo` per `README.md`). Criteria 3 and 5 are coded in `services/audit/src/audit/anchor.py` (`Anchorer`), `services/audit/src/audit/worker.py`, `db/policies/31_audit_sealed.sql` (`audit_checkpoint`, `audit_anchor_leaves`) and `aws_s3_bucket.anchor` with Object Lock (`infra/aws/main.tf`), untested. Criterion 6 is partly coded: `organizations.retention_days default 2190` and `legal_hold` columns, trigger `documents_legal_hold` (`db/policies/11_access.sql`), retention clock in `services/identity/src/identity/destruction.py`. Criteria 2 and 7 were not found (criterion 7 is open question Q-08).

### Requirement 62: Audit coverage and read scopes

**ID:** R-62 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin, Admin, Tenant, operator · **Design:** §13.4, §13.5, §5.2 audit rows · **Gates:** G9.1, G9.7

**User Story:** As each kind of viewer, I want to see exactly the audit events and payloads my role allows, so that oversight never becomes a content leak.

#### Acceptance Criteria

1. THE Platform SHALL record identity events (login, MFA failure, token rejected, step-up, authenticator changes), onboarding events (code verification with the true failure reason, membership created, approved, rejected), governance events (code rotation, state and policy changes, governance steps, walls, break-glass and emergency sessions, successor transfer, key operations), data events (upload, delete, grant and visibility changes, full query chain, export, downloads), system events (validation outcome, cache hit, tokens dropped, quota hit, vector-versus-Postgres mismatch, reconciler repairs) and every operator JIT grant, session and action.
2. THE Audit_Service SHALL show the Super Admin organization-level and admin-level events and tenant activity as aggregate counts only, and never payloads.
3. THE Audit_Service SHALL show an admin the whole workspace's events and payloads per workspace policy.
4. THE Audit_Service SHALL show a tenant their own history, including break-glass sessions that touched their documents, and their own payloads.
5. THE Audit_Service SHALL show platform operators infrastructure events only and never payloads.
6. THE Audit_Service SHALL write every operator action to the affected organization's audit view.

**Status:** Partial

**Evidence:** Criteria 2, 3 and 4 are partly met in `services/audit/src/audit/service.py` (`_scope` per role, titles shown only to people who can see the document, filters in SQL); MVP payloads hold hashes and counts, so payload policy and the break-glass part of criterion 4 do not apply yet. Criterion 1 is partly met: onboarding, code, membership, upload, delete and query events are written (`services/identity/src/identity/service.py`, `services/ingestion/src/ingestion/documents.py`); login, MFA, step-up, export and download events were not found. Criteria 5 and 6 are coded for JIT grants in `services/ops/src/ops/jit.py`; the operator plane is flag-gated.

### Requirement 63: Detection signals and alerting

**ID:** R-63 · **Type:** NFR · **Priority:** P1 · **Persona:** Security on-call · **Design:** §10.1 L5, §13.6, DEF-08 · **Gates:** G9.3

**User Story:** As a security on-call engineer, I want alerts built from signals that actually exist and drilled for real, so that isolation failures are detected and reach me.

#### Acceptance Criteria

1. THE Platform SHALL raise alerts at the §13.6 severities for: write rejected by a policy (SQLSTATE 42501); a vector hit PostgreSQL refused; out-of-scope resource IDs (404) in bursts or enumeration patterns; boot self-test failure or FORCE-RLS or role-attribute drift; canary and provenance test failures; bursts of failed code attempts, Organization Code use from a new country, or one user in two countries at once; admin or Super Admin role assigned outside an approved membership; admins pending beyond N days or approval followed by bulk tenant creation; any break-glass, emergency or operator session and unreviewed emergency access at 48 and 72 hours; failed audit-chain or anchor verification; KMS deletion, disable or key-policy events and unusual KMS volume (page within 60 seconds); tokens minted outside the Gateway identity or certificate issuance spikes; unusual token spend per workspace and quota at 80 percent.
2. THE Audit_Service SHALL deliver each open alert once to a real on-call channel and retry until delivery succeeds.
3. THE Test_Suite SHALL include a drill test for every alert that triggers it for real and checks delivery within its target.
4. THE Platform SHALL run a nightly schema audit for FORCE-RLS and role-attribute drift.

**Status:** Partial

**Evidence:** Criterion 2 is coded in `services/audit/src/audit/alerts.py` (`Alerting.deliver` to `ONCALL_WEBHOOK_URL`, dedup key) with table `alerts` (`db/migrations/0007_identity_production.sql`). Some signals in criterion 1 are coded: review overdue 48 h and 72 h (`services/identity/src/identity/scope_admin.py`, `sweep`), reconciler scope mismatch (`services/ingestion/src/ingestion/production.py`), KeyGuard events (`infra/keyguard/responder.py`), Auth0 role reconciliation (`services/identity/src/identity/lifecycle.py`). Most other signals and criteria 3 and 4 were not found. All flag-gated or worker-only and untested.

### Requirement 64: Hierarchical quotas and noisy-neighbor control

**ID:** R-64 · **Type:** NFR · **Priority:** P1 · **Persona:** Super Admin, Admin · **Design:** §13.7, §10.8 · **Gates:** G3.9, G9.4

**User Story:** As a workspace admin, I want limits enforced at organization, workspace and tenant level across replicas, so that one heavy user or workspace cannot degrade others or exhaust the LLM budget.

#### Acceptance Criteria

1. THE Gateway SHALL allow a request only if the tenant, workspace and organization budgets all have room, with organization plan limits (admins, tenants per admin, storage, ingestion pages, LLM tokens per day) as the ceiling.
2. THE Identity_Service SHALL reject admin-assigned workspace or tenant limits that exceed the organization ceiling.
3. THE Gateway SHALL enforce per-tenant query rates and a per-workspace generation concurrency cap in Valkey across replicas.
4. WHEN a budget reaches 80 percent, THE Platform SHALL raise a spend alert, and THE Generation_Service SHALL protect the LLM provider budget with circuit breakers.

**Status:** Partial

**Evidence:** Criteria 1, 3 and 4 are coded in `services/gateway/src/gateway/quotas.py` (`Quotas.admit_query` tenant → workspace → organization, 80 percent alert, `CircuitBreaker`) and `services/gateway/src/gateway/trust.py` (`RateLimiter` on Valkey with local fallback), used only by the flag-gated streaming route. The MVP uses in-process `SlidingWindow` limits per user (`services/gateway/src/gateway/app.py`) (DEV-27). Criterion 2: table `quotas` exists (`db/migrations/0006_production_core.sql`); no `PUT /v1/org/admins/{id}/quotas` route exists.

### Requirement 65: Compliance mapping for counsel review

**ID:** R-65 · **Type:** NFR · **Priority:** P2 · **Persona:** Counsel · **Design:** §13.9, §2.1 goal 5, §18 `docs/compliance/` · **Gates:** G10.10, G11.4

**User Story:** As counsel, I want a maintained mapping from HIPAA and legal-confidentiality requirements to design elements, so that I can review the system's compliance position.

#### Acceptance Criteria

1. THE Platform SHALL maintain the §13.9 compliance mapping in `docs/compliance/` covering HIPAA access control, emergency access, audit controls, integrity, authentication, transmission security, minimum necessary, documentation retention, processor BAAs, attorney-client privilege and ethical screening.
2. THE Platform SHALL mark the mapping as a design aid, not legal advice, and include it in the external review package.

**Status:** Not started

**Evidence:** No `docs/compliance/` directory exists (`docs/` holds `adr/`, `runbooks/`, `mvp.md`, `production.md`, `user-guide.md`, `versions.md`).

### Requirement 66: Operator identity and roles

**ID:** R-66 · **Type:** FR · **Priority:** P1 · **Persona:** Platform operator · **Design:** §3.1 principle 5, §14.1, §14.2, DEF-25, D24 · **Gates:** G9.7

**User Story:** As a customer, I want platform staff to sign in through a separate identity provider with named roles and no standing access, so that our own staff are held to least privilege.

#### Acceptance Criteria

1. THE Ops_Service SHALL authenticate operators only through a separate identity provider (a dedicated `platform-<env>` Auth0 tenant or the company IdP), never a customer Auth0 tenant, with passkeys mandatory and a device certificate required at the operator ingress.
2. THE Ops_Service SHALL take operator roles from `ops.operator_accounts`, not token claims, with the roles `operator_sre`, `operator_support`, `security_officer`, `key_custodian` and `operator_admin` and the permissions and prohibitions of the §14.2 table.
3. THE Platform SHALL ensure that at least two key custodians exist and that a key custodian is never the same human as a `security_officer`.
4. THE Platform SHALL keep operator accounts as named, background-checked, trained individuals, reviewed quarterly and removed the day they leave.

**Status:** Partial

**Evidence:** Criteria 1 (separate IdP part) and 2 are coded in `services/ops/src/ops/app.py` (`OPS_AUTH0_DOMAIN`, `OPS_AUDIENCE`, roles from `ops.operator_accounts`) and `db/migrations/0006_production_core.sql` (`ops.operator_accounts`). Device certificates, passkey enforcement, the custodian constraints of criterion 3 and the process in criterion 4 were not found. The `operator_plane` flag is off.

### Requirement 67: Operator JIT access types, limits and lifecycle

**ID:** R-67 · **Type:** FR · **Priority:** P1 · **Persona:** Platform operator, Super Admin, Admin · **Design:** §14.3, §14.4, §6.8 · **Gates:** G9.7

**User Story:** As a workspace admin, I want any operator access to my content to need my approval, expire on its own and show in my audit, so that support never becomes standing access.

#### Acceptance Criteria

1. WHEN an operator requests infrastructure access, THE Ops_Service SHALL require approval by a different `security_officer` or `operator_sre` and grant a short-lived role through a recorded access broker, with database access limited to ephemeral `ops_metadata_ro` credentials.
2. WHEN an operator requests control-plane metadata access, THE Ops_Service SHALL require the organization's Super Admin's approval and grant a read-only, scoped support principal minted by the Gateway.
3. WHEN an operator requests content access, THE Ops_Service SHALL require the workspace admin's approval and grant a read-only, no-export support principal limited to the named documents or queries.
4. THE Ops_Service SHALL limit sessions to: infrastructure 4 hours default and 24 hours maximum; control-plane metadata 4 hours and 8 hours; content 1 hour and 4 hours; an approved request unused for 24 hours SHALL expire; renewal SHALL need a new approval.
5. WHEN a session expires or is revoked, THE Ops_Service SHALL end access (broker role revoked, or support principal's `pv` bumped).
6. THE Ops_Service SHALL write every grant to the customer's audit view, produce a monthly per-organization operator access report and keep the operator audit as its own anchored hash chain.
7. IF the customer is unreachable, THEN THE Ops_Service SHALL allow infrastructure stabilization only and no content access.

**Status:** Partial

**Evidence:** Criteria 1 (approval part), 2, 3, 4 and 6 (customer audit part) are coded in `services/ops/src/ops/jit.py` (`JitAccess.request`, `approve_as_operator`, `approve_as_customer`, `revoke`, `expire_due`, maximums 24 h, 8 h and 4 h) and `services/ops/src/ops/app.py`; the workspace operator-approval routes are absent from `contracts/authz-matrix.yaml`. The access broker, Gateway-minted support principal, monthly report and separate operator chain were not found. Flag off, untested.

### Requirement 68: Operator prohibitions

**ID:** R-68 · **Type:** NFR · **Priority:** P1 · **Persona:** Customer · **Design:** §14.5 · **Gates:** G9.7

**User Story:** As a customer, I want hard limits on what operators can ever do, enforced by roles and key policies, so that insider risk is bounded by design.

#### Acceptance Criteria

1. THE Platform SHALL prevent operators from reading content without customer approval, holding a standing database superuser or migration-owner credential, signing context tokens, releasing a sealed workspace alone, destroying keys alone, approving their own access and disabling the audit path.
2. THE Test_Suite SHALL test each prohibition.

**Status:** Partial

**Evidence:** Self-approval is refused in `services/ops/src/ops/jit.py` and by a database CHECK on `ops.operator_access_grants` (`db/migrations/0006_production_core.sql`); destroying keys alone is refused by `libs/lmqa_keys/src/lmqa_keys/keyguard.py`. The other prohibitions and criterion 2 were not found.

### Requirement 69: Owner recovery

**ID:** R-69 · **Type:** FR · **Priority:** P1 · **Persona:** Super Admin, operators · **Design:** §14.6, §6.7 `owner_recovery`, DEF-60, D3 · **Gates:** G9.11

**User Story:** As an organization whose owner lost access, I want a slow, verified, vetoable recovery path, so that recovery is possible without becoming a takeover route.

#### Acceptance Criteria

1. WHEN the organization's authorized signatory requests recovery, THE Identity_Service SHALL create an `owner_recovery` governance request initiated by `operator_support` and approved by a `security_officer` and a different `operator_support` lead (three distinct operators).
2. WHEN recovery is requested, THE Identity_Service SHALL notify every admin and any co-owner, any of whom can veto.
3. WHEN the 72-hour wait ends without a veto, THE Identity_Service SHALL attach a new Super Admin identity, require it to enroll two passkeys and block the old identity.
4. THE Audit_Service SHALL record the whole path.

**Status:** Partial

**Evidence:** Criteria 1 and 2 are coded in `services/identity/src/identity/governance.py` (`KindRule` for `owner_recovery`, `veto`) with `owner_recovery_wait = 72 h` (`libs/lmqa_models/src/lmqa_models/policy.py`). No effect function for `owner_recovery` is registered in `services/identity/src/identity/worker.py` (`build`), so criterion 3 is not met. `docs/runbooks/org-recovery.md` exists.

### Requirement 70: API rules for every endpoint

**ID:** R-70 · **Type:** IR · **Priority:** P0 · **Persona:** Engineer · **Design:** §15.1 · **Gates:** G3.6, G3.7, G3.9

**User Story:** As a client developer, I want uniform API rules for IDs, errors, idempotency and contracts, so that every endpoint behaves predictably and securely.

#### Acceptance Criteria

1. THE Gateway SHALL use opaque UUIDs for all IDs and SHALL never accept `org_id` or `workspace_id` in paths, queries or bodies.
2. THE Gateway SHALL accept an `Idempotency-Key` on every state-changing POST, PUT, PATCH and DELETE and apply each effect once, and WHEN a key is replayed with the same body, THE Gateway SHALL return the original response.
3. THE Gateway SHALL return errors as `application/problem+json` (RFC 9457) with uniform text for security-sensitive failures.
4. THE Platform SHALL publish an OpenAPI document per service under `contracts/openapi/` and derive the route allow-list, the generated frontend client and the authorization tests from those documents and `contracts/authz-matrix.yaml`.
5. THE Test_Suite SHALL fuzz every endpoint with each role's token (Schemathesis) and accept only expected 2xx and 4xx responses.

**Status:** Partial

**Evidence:** Criterion 1 is met in `services/gateway/src/gateway/app.py` (UUID path parameters, no organization or workspace fields). Criterion 4 is partly met: `contracts/openapi/gateway.json` (one document for the Gateway only) exported by `tools/export_openapi.py`, typed client generation (`frontend/package.json`, `gen:api`). Criterion 2 is coded in `IdempotencyStore` (`services/gateway/src/gateway/trust.py`) but no route calls it. Criterion 3 is not met: errors are `{"detail": ...}` JSON. Criterion 5: no fuzz tests exist.

### Requirement 71: Onboarding and session endpoints

**ID:** R-71 · **Type:** IR · **Priority:** P0 · **Persona:** New user, all members · **Design:** §15.2, §15.3, DEF-59 · **Gates:** G2.4, G3.6

**User Story:** As a new or pending user, I want the onboarding and session endpoints of §15.2 and §15.3, so that I can join and see my own principal and authenticators.

#### Acceptance Criteria

1. THE Gateway SHALL expose, for the `onboarding` audience only: `POST /v1/onboarding/organization`, `POST /v1/onboarding/join-admin`, `POST /v1/onboarding/join-tenant/preview`, `POST /v1/onboarding/join-tenant` and `GET /v1/onboarding/status`.
2. THE Gateway SHALL expose `GET /v1/me` (principal, states, capabilities, `auth_strength`, `has_backup_authenticator`, with capabilities limited to enrollment and status while the organization is `pending`) and `GET /v1/me/authenticators` (count and types, no secrets).

**Status:** Partial

**Evidence:** `contracts/authz-matrix.yaml` and `services/gateway/src/gateway/app.py` expose `POST /v1/onboarding/organization`, `join-admin`, `preview-tenant` (path differs), `join-tenant`, plus an extra `DELETE /v1/onboarding/request`, all for any authenticated token rather than an onboarding audience. `GET /v1/me` exists without `auth_strength` or `has_backup_authenticator` (`IdentityService.me`). `GET /v1/onboarding/status` and `GET /v1/me/authenticators` are absent (DEV-26).

### Requirement 72: Organization endpoints

**ID:** R-72 · **Type:** IR · **Priority:** P1 · **Persona:** Super Admin, co-owner · **Design:** §15.4 · **Gates:** G3.6

**User Story:** As a Super Admin, I want the organization endpoints of §15.4, so that I can manage settings, codes, invites, admins, quotas, workspaces, audit and the co-owner.

#### Acceptance Criteria

1. THE Gateway SHALL expose for `SA`: `GET /v1/org` and `PATCH /v1/org/settings` (step-up on PATCH; approval mode, retention schedule, deployment type, region, SSO connection, delivery defaults); `POST /v1/org/code` and `POST /v1/org/code/rotate` (step-up); `POST /v1/org/invites` (step-up; kinds `admin` and `successor`); `GET /v1/org/admins` and `GET /v1/org/admins/{id}` (counts only, never tenants); `POST /v1/org/admins/{id}/approve`, `/reject`, `/suspend`, `/reactivate` (step-up; co-owner for owner-linked admins); `DELETE /v1/org/admins/{id}` (step-up; workspace frozen); `PUT /v1/org/admins/{id}/quotas` (step-up); `GET /v1/org/workspaces` and `GET /v1/org/workspaces/{id}` (metadata and state only); `GET /v1/org/audit`; `POST /v1/org/co-owner/invite` and `DELETE /v1/org/co-owner` (step-up).
2. THE Gateway SHALL expose `POST /v1/org/co-owner/accept` (step-up) to the invitee.

**Status:** Partial

**Evidence:** `contracts/authz-matrix.yaml` exposes `GET /v1/org/admins`, `POST /v1/org/admins/{membership_id}/{action}` (approve, reject, suspend, reactivate), `GET /v1/org/code` and `POST /v1/org/code` (generate and rotate in one), without step-up. Organization audit is served by the shared `GET /v1/audit`. The other §15.4 endpoints are absent.

### Requirement 73: Governance request endpoints

**ID:** R-73 · **Type:** IR · **Priority:** P1 · **Persona:** Super Admin, Admin · **Design:** §15.5, §6.7 · **Gates:** G2.10, G3.6

**User Story:** As an initiator or approver, I want the governance endpoints of §15.5, so that two-person actions can be created, inspected, approved, rejected and cancelled.

#### Acceptance Criteria

1. THE Gateway SHALL expose `POST /v1/governance-requests` (SA or AD per kind; step-up; kinds `successor_transfer`, `private_read_enable`, `wall_lift`, `workspace_unseal`, `workspace_destroy`, `org_delete`, `co_owner_set`), `GET /v1/governance-requests` and `GET /v1/governance-requests/{id}` (within scope), `POST /v1/governance-requests/{id}/approve` (approver set; step-up; a different human from the initiator and other approvers), and `POST /v1/governance-requests/{id}/reject` and `/cancel`.
2. THE Identity_Service SHALL always allow the initiator to cancel.

**Status:** Partial

**Evidence:** `GET /v1/governance`, `POST /v1/governance` and `POST /v1/governance/{request_id}/{action}` exist with step-up behind the disabled `governance_requests` flag (`contracts/authz-matrix.yaml`, `services/gateway/src/gateway/production.py`); paths differ from the design (DEV-26). Criterion 2 is coded in `GovernanceService.cancel` (`services/identity/src/identity/governance.py`).

### Requirement 74: Workspace endpoints

**ID:** R-74 · **Type:** IR · **Priority:** P1 · **Persona:** Admin · **Design:** §15.6 · **Gates:** G3.6

**User Story:** As an admin, I want the workspace endpoints of §15.6, so that I can manage policy, codes, tenants, grants, matters, walls, break-glass, held documents, reviews, operator approvals and audit.

#### Acceptance Criteria

1. THE Gateway SHALL expose for `AD`: `GET` and `PATCH /v1/workspace/policy` (step-up on PATCH); `POST /v1/workspace/code` and `/code/rotate` (step-up); `GET /v1/workspace/tenants`; `POST /v1/workspace/tenants/{id}/approve`, `/reject`, `/suspend`, `/reactivate`; `DELETE /v1/workspace/tenants/{id}` (step-up); `PUT /v1/workspace/tenants/{id}/grants`; `GET`, `POST`, `PATCH`, `DELETE /v1/workspace/matters[/{id}]`; `GET` and `POST /v1/workspace/walls`; `GET` and `POST /v1/workspace/break-glass` (step-up) and `POST /v1/workspace/break-glass/{id}/end`; `GET /v1/workspace/held-documents`, `POST /v1/workspace/held-documents/{id}/reassign` and `DELETE /v1/workspace/held-documents/{id}` (step-up); `GET /v1/workspace/review-queue` and `POST /v1/workspace/review-queue/{id}/close`; `GET /v1/workspace/operator-access-requests` and `POST .../{id}/approve` (step-up), `/deny`, `/revoke`; `GET /v1/workspace/audit`.

**Status:** Partial

**Evidence:** The MVP exposes `GET /v1/workspace/members`, `POST /v1/workspace/members/{membership_id}/{action}` and `GET` and `POST /v1/workspace/code` (`contracts/authz-matrix.yaml`), without step-up. Behind the disabled `matters_walls_tiers` flag: `GET` and `POST /v1/workspace/matters`, grants as `POST /v1/workspace/matters/{matter_id}/grants` and `DELETE .../grants/{user_id}`, walls as `POST /v1/workspace/matters/{matter_id}/walls`, `POST /v1/break-glass`, `DELETE /v1/break-glass/{session_id}`, `GET /v1/reviews`, `POST /v1/reviews/{task_id}/close`. Policy, tenant removal, held documents, operator approvals and workspace audit endpoints are absent (DEV-26).

### Requirement 75: Data plane endpoints

**ID:** R-75 · **Type:** IR · **Priority:** P0 · **Persona:** Admin, Tenant · **Design:** §15.7 · **Gates:** G3.6, G4.1, G7.10

**User Story:** As an admin or tenant, I want the data plane endpoints of §15.7, so that I can query, manage documents, review OCR, open citations, export, use emergency access and read my audit.

#### Acceptance Criteria

1. THE Gateway SHALL expose for `AD` and `TE`: `POST /v1/query` (SSE; optional `matter_ids` that can only narrow scope); `GET /v1/documents` and `GET /v1/documents/{id}`; `POST /v1/documents/uploads` and `POST /v1/documents/{id}/complete`; `PATCH /v1/documents/{id}` (owner; writes the outbox row); `DELETE /v1/documents/{id}` (owner; crypto-erase); `GET /v1/documents/{id}/download`; `POST /v1/documents/{id}/ocr-review` (owner); `GET /v1/citations/{request_id}/{alias}` (visibility re-checked); `POST /v1/exports` (step-up); `GET /v1/audit/me`.
2. THE Gateway SHALL expose `POST /v1/access/emergency`, `POST /v1/access/emergency/{id}/end` and `GET /v1/access/emergency` to tenants in medical workspaces.
3. THE Gateway SHALL expose `GET /v1/health` anonymously with liveness only and no detail.

**Status:** Partial

**Evidence:** The MVP exposes `GET /v1/documents`, `GET /v1/documents/{doc_id}`, `POST /v1/documents` (single-step multipart), `DELETE /v1/documents/{doc_id}`, `POST /v1/queries` (JSON, buffered), `GET /v1/queries/{query_id}`, `GET /v1/audit` and the flag-gated `POST /v1/queries/stream` (`contracts/authz-matrix.yaml`). `GET /v1/health` exists but returns model and re-ranker details (`services/gateway/src/gateway/app.py`, `health`), which breaks "no detail" in criterion 3. Emergency access is `POST /v1/emergency-access` behind a disabled flag. Two-step upload, `PATCH`, download, OCR review, citations, exports and `GET /v1/audit/me` are absent (DEV-22, DEV-26).

### Requirement 76: Operator plane endpoints

**ID:** R-76 · **Type:** IR · **Priority:** P1 · **Persona:** Platform operator · **Design:** §15.8 · **Gates:** G9.7

**User Story:** As an operator, I want the operator endpoints of §15.8 on a separate ingress, so that JIT access, holds, recoveries, KeyGuard and the operator audit are reachable only there.

#### Acceptance Criteria

1. THE Ops_Service SHALL expose on `ops.<product-domain>`, behind a separate ingress and identity provider: `POST /ops/v1/access-requests`; `GET /ops/v1/access-requests` and `POST /ops/v1/access-requests/{id}/approve`, `/deny`, `/revoke`; `GET /ops/v1/orgs` and `GET /ops/v1/orgs/{id}`; `POST /ops/v1/orgs/{id}/freeze` (`security_officer`, instant); `POST /ops/v1/orgs/{id}/release` (`security_officer` plus a second operator); `POST /ops/v1/recoveries` and `POST /ops/v1/recoveries/{id}/approve`; `POST /ops/v1/keyguard/requests` and `POST /ops/v1/keyguard/requests/{id}/approve` (`key_custodian`); `GET /ops/v1/audit` (`security_officer`).

**Status:** Partial

**Evidence:** `services/ops/src/ops/app.py` defines access request, approve and revoke routes and a KeyGuard decision route (`keyguard_decide`), run on 127.0.0.1:8006 by `make ops`. Deny, organization listing, freeze, release, recoveries and operator audit routes are absent.

### Requirement 77: Internal endpoints

**ID:** R-77 · **Type:** IR · **Priority:** P0 · **Persona:** Engineer · **Design:** §15.9 · **Gates:** G3.3, G5.2

**User Story:** As a service owner, I want internal endpoints that are unreachable from outside and accept only Context_Tokens, so that service calls follow one audited path.

#### Acceptance Criteria

1. THE Platform SHALL expose under `/internal/v1/` only on the internal network: identity `principal/{sub}`, `revocations`, `provisioning/*`; retrieval `search`, `scope/{request_id}` (operator-approved diagnostics); generation `answer` (SSE); citation_validator `validate-stream` and `validate-answer`; ingestion `documents/*`, `documents/{id}/versions`, `index/reconcile`; audit `events`, `payloads/{id}`, `verify`, `anchors`.
2. THE services SHALL accept on internal endpoints only requests carrying a valid Context_Token for their audience and the caller's own service credential.

**Status:** Not started

**Evidence:** No `/internal/v1/` route exists in any service; the services are called in-process by the Gateway (`services/gateway/src/gateway/app.py`, `Services`). `libs/lmqa_auth/src/lmqa_auth/internal.py` (`context_dependency`) is defined but not used.

### Requirement 78: Data model conventions and core tables

**ID:** R-78 · **Type:** DR · **Priority:** P0 · **Persona:** Engineer · **Design:** §16.1, §16.2, DEF-48, DEF-49 · **Gates:** G1.1, G1.6

**User Story:** As an engineer, I want one data model with the conventions and tables of §16, so that every service builds on the same, safe schema.

#### Acceptance Criteria

1. THE Database SHALL use UUIDv7 primary keys, `timestamptz` everywhere, `org_id` and where applicable `workspace_id` on every tenant-bearing table, composite foreign keys, FORCE RLS on every table, enum status columns with transition tables, and hashed or wrapped storage for codes and keys.
2. THE Database SHALL provide the core tables of §16.2: `orgs`, `users`, `memberships` (unique on `user_id` in v1; `approved_by` ≠ `user_id`), the `principal_v` view, `workspaces`, `join_codes`, `join_attempts`, `governance_requests`, `governance_approvals`, `matters`, `matter_grants`, `matter_walls`, `access_exceptions`, `break_glass_sessions`, `documents` (with `retention_until` and `legal_hold`), `document_versions`, `doc_keys`, `workspace_keys`, `org_keys`, `audit_keys`, `chunks`, `retrieval_records`, `index_outbox`, `idempotency_keys`, `audit_event`, `audit_payload`, `audit_anchor`, `deletion_tombstones`, `quotas`, `workspace_usage`, `operator_accounts` and `operator_access_grants` (separate schema).
3. THE Database SHALL maintain `scope_version` and `scope_hash` on memberships through triggers on grants, walls, exceptions, sessions and workspace flags.
4. WHEN migrations are applied and rolled back on an empty and a populated database, THE Database SHALL match the schema snapshot.

**Status:** Partial

**Evidence:** Criteria 2 and 3 are largely coded in `db/migrations/0001_schema.sql` to `0008_streaming_release.sql` and `db/policies/11_access.sql` (table names differ: `organizations`, `audit_events`, `audit_anchors`, no separate `audit_payload` table; `workspace_usage`, `ops.operator_accounts`, `ops.operator_access_grants` exist). Criterion 1 is partly met: new tables use `uuidv7()` (`0006`), MVP tables use `gen_random_uuid()`; statuses are text with CHECK constraints; FORCE RLS in `db/policies/15_force_rls.sql`. The MVP migrations are applied by `tools/db_migrate.py`; 0006 to 0008 were never applied (`docs/production.md`). No rollback migrations and no schema snapshot exist (criterion 4).

### Requirement 79: Database role policy summary

**ID:** R-79 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §16.3 · **Gates:** G1.2, G1.5

**User Story:** As a security reviewer, I want each database role limited to the tables of §16.3, so that compromising one service exposes only its own slice.

#### Acceptance Criteria

1. THE Database SHALL limit `svc_gateway` to the `principal_v` view and `audit_append` execute.
2. THE Database SHALL limit `svc_identity` and the `super_admin` policy set to control-plane tables (full for identity, a restricted subset for the Super Admin), with no content tables and `audit_append` plus organization-scope events for audit.
3. THE Database SHALL give `svc_ingestion`, `svc_retrieval`, `svc_generation` and `svc_validator` read-only control-plane context, content per §5.4 under RLS, `retrieval_records` per §16.2 and `audit_append` execute.
4. THE Database SHALL give `svc_audit_reader` audit events and payload decryption only, `reconciler` column-level SELECT on IDs and index metadata, and `ops_metadata_ro` metadata views and the operator chain only.

**Status:** Partial

**Evidence:** All four criteria are coded in `db/roles/grants.sql` (production service roles block) and `db/policies/15_force_rls.sql` (`identity_all`, `ops_meta_usage`). The running MVP uses only `lmqa_app` and `lmqa_system` (DEV-13), and the production roles exist only "for roles that exist".

### Requirement 80: Frontend structure and role routing

**ID:** R-80 · **Type:** FR · **Priority:** P1 · **Persona:** All users · **Design:** §17.1, DEF-36 · **Gates:** G8.1

**User Story:** As a user, I want the interface to show only the routes my role may use and to hide the rest as 404, so that the UI never reveals what I cannot reach.

#### Acceptance Criteria

1. THE Frontend SHALL use `src/proxy.ts` (not `middleware.ts`) for Auth0 route mounting, the session gate and the CSP nonce, and `src/lib/` for `auth0.ts`, the generated API client, `sse.ts` and `capabilities.ts`.
2. THE Frontend SHALL provide the route groups `(onboarding)`, `(app)/chat`, `(app)/library`, `(app)/audit`, `(super-admin)/manage-admins`, `(super-admin)/governance`, `(workspace-admin)/manage-tenants`, `(workspace-admin)/walls`, `(workspace-admin)/review`, `(account)` and `api/` (BFF handlers, the only code that holds tokens).
3. THE Frontend SHALL route per the §17.1 table: members are redirected away from `/onboarding`; the Super Admin is redirected from `/chat` and `/library` to Manage Admins; `/manage-admins` and organization-level `/governance` are Super Admin only; `/manage-tenants`, `/walls` and `/review` are admin only; every forbidden route returns 404; pending or suspended users are blocked.
4. THE Frontend SHALL obtain the resolved principal and capability list from the BFF `/me` handler and SHALL never trust a role decoded in the browser.
5. THE Frontend SHALL let admins start `wall_lift` and `private_read_enable` requests from `/walls` and the policy tab of `/manage-tenants`.

**Status:** Partial

**Evidence:** Criterion 1 is partly met: `frontend/src/proxy.ts`, `frontend/src/lib/auth0.ts`, `api-client.ts`, `sse.ts` (no `capabilities.ts`). Criterion 4 is met: `frontend/src/lib/backend.ts` (`requireMe`) and the role layouts. Criterion 3 is met for existing routes: `frontend/src/app/(super-admin)/layout.tsx` and `(workspace-admin)/layout.tsx` call `notFound()` for other roles; `make demo-web` checks role routing (`README.md`). Criterion 2 is partly met: existing routes are `(onboarding)/onboarding`, `(app)/chat`, `(app)/library`, `(app)/audit`, `(super-admin)/manage-admins`, `(super-admin)/org-governance`, `(workspace-admin)/manage-tenants`, `(workspace-admin)/governance`, `(workspace-admin)/matters`, `(workspace-admin)/reviews`, `(account)/profile`, `api/backend`; `/walls` and `/review` are absent under those names. Criterion 5 is coded in `frontend/src/components/governance/governance-center.tsx`, flag-gated. The app also serves a public website under `(site)` (DEV-21).

### Requirement 81: Frontend key surfaces

**ID:** R-81 · **Type:** FR · **Priority:** P1 · **Persona:** All users · **Design:** §17.2 · **Gates:** G8.3, G8.9

**User Story:** As each kind of user, I want the chat, library, management and account surfaces of §17.2, so that every workflow in the design has a screen.

#### Acceptance Criteria

1. THE Frontend SHALL render chat sentences only after validation, each with citation markers; a side panel SHALL show the chunk, page range and highlighted span for a clicked marker; stripped sentences SHALL show the visible "could not be verified" marker; status events SHALL keep the interface responsive while the first sentence validates.
2. THE Frontend SHALL provide a library with upload progress, per-document status including `ocr_review` with a side-by-side page image and text editor, visibility and matter controls and the confidentiality tier.
3. THE Frontend SHALL provide Manage Admins for the Super Admin: admins table (state, last active, tenant count, document count, 30-day token usage) with pending requests pinned; row actions with step-up and a reason; an Organization Code panel (lookup ID, dates, uses remaining, rotate, email-bound invite, copy-and-clear modal); an admin drawer with counts only; organization settings; co-owner management; and a governance center.
4. THE Frontend SHALL provide Manage Tenants for admins: tenants table with pending pinned; approve with a grants selector; a grants editor with a preview of what the tenant could retrieve; an Admin Code panel with join-policy selector; workspace policy; the holding queue (metadata only); walls with a lift workflow; break-glass sessions; operator access approvals; and the review queue.
5. THE Frontend SHALL provide an account page with the authenticator list (count and type), a backup authenticator prompt and active sessions with sign-out.

**Status:** Partial

**Evidence:** Criterion 1 is met for buffered answers: `frontend/src/components/chat/chat.tsx`, `answer-view.tsx`, `citation-panel.tsx` (highlights rendered as text nodes); `streaming-chat.tsx` is flag-gated. Criteria 3 and 4 are partly met: `frontend/src/components/manage/manage-admins.tsx`, `manage-tenants.tsx`, `code-panel.tsx`, `matters.tsx`, `reviews.tsx`; no step-up, invites, co-owner, grants preview, holding queue or operator approvals. Criterion 2 is partly met: `frontend/src/components/library/library.tsx` (upload, status, visibility); no OCR review or tier. Criterion 5 is not met: `frontend/src/components/account/profile-form.tsx` edits name, job title, department and phone (DEV-21) with no authenticator or session list.

### Requirement 82: Frontend security, streaming and accessibility

**ID:** R-82 · **Type:** NFR · **Priority:** P1 · **Persona:** All users · **Design:** §17.3, §4.8, DEF-36, DEF-58, DEF-61, D15, D30 · **Gates:** G8.4 to G8.8, G8.10

**User Story:** As a user, I want a hardened, accessible interface that streams correctly at every byte boundary, so that the browser cannot be used to steal sessions or render hostile content.

#### Acceptance Criteria

1. THE Frontend SHALL set a strict CSP from `proxy.ts` on every response: `script-src` with a per-request nonce and `strict-dynamic`, no inline scripts, no `unsafe-eval`, `frame-ancestors 'none'`, Trusted Types where supported, and `Referrer-Policy: no-referrer` on onboarding.
2. THE Frontend SHALL render document content through a sanitized viewer with no raw HTML injection.
3. THE Frontend SHALL keep tokens out of browser storage, cookie values and response bodies, holding only an opaque httpOnly SameSite session ID.
4. THE Frontend SHALL accept dynamic rendering for nonce-based CSP while keeping static assets cacheable.
5. THE Frontend SHALL parse SSE with `eventsource-parser` (a buffered parser), and FOR ALL slicings of a real stream at every byte boundary, THE Frontend SHALL render identically (property test).
6. THE Frontend SHALL not use the Vercel AI SDK.
7. THE Frontend SHALL render secrets once, copy them through a button and clear them from state on close, and SHALL show the effect of destructive actions on sessions and data before confirming.
8. THE Frontend SHALL call the Gateway only through a client generated from the OpenAPI contracts (`openapi-typescript` and `openapi-fetch`), enforced by an ESLint restricted-imports rule.
9. THE Frontend SHALL ship as a containerized standalone build behind the same ingress as the API, with no Vercel dependency.
10. THE Frontend SHALL meet WCAG 2.2 AA, verified by axe (zero serious or critical issues) and keyboard-only end-to-end flows.
11. THE Toolchain SHALL check the Frontend with ESLint (flat config, `typescript-eslint` strict-type-checked, Next.js plugin) with zero warnings, `tsc --noEmit`, Vitest and a bundle budget.

**Status:** Partial

**Evidence:** Criteria 1 (nonce, `strict-dynamic`, `frame-ancestors 'none'`, `object-src 'none'`), 4 and 6 are met in `frontend/src/proxy.ts`, `frontend/next.config.ts` and `frontend/package.json`; `unsafe-eval` is added only in development, `style-src 'unsafe-inline'` is allowed and Trusted Types are absent (DEV-34). Criterion 3 is met for the token endpoint (`enableAccessTokenEndpoint: false`) but sessions use the SDK cookie by default (R-20). Criterion 5 uses a custom parser `frontend/src/lib/sse.ts` (`SseParser`) instead of `eventsource-parser`, with Vitest configured (`frontend/vitest.config.ts`); no byte-boundary test was found. Criterion 7 is partly met by `frontend/src/components/manage/code-panel.tsx` (shown once). Criterion 8 is partly met: types are generated (`frontend/src/lib/api-schema.d.ts`) but `frontend/src/lib/api-client.ts` is a hand-written `fetch` wrapper. Criterion 9: `frontend/Dockerfile` exists. Criterion 11 is partly met: `frontend/eslint.config.mjs` and `typecheck`; `docs/production.md` reports 44 ESLint findings. Criteria 2 and 10 were not found.

### Requirement 83: Planes, service catalog and deployables

**ID:** R-83 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §2.1 goals 6 and 7, §3.1 principles 4 and 8, §4.1, §4.2, §4.3, DEF-42 · **Gates:** G3.3, G5.2, G10.4

**User Story:** As an engineer, I want each service built as its own deployable with its own image, database role and credentials across three planes, so that the data plane, control plane and operations plane scale and fail independently.

#### Acceptance Criteria

1. THE Platform SHALL separate a data plane (Gateway data routes, Ingestion, Retrieval, Generation, Validator, Audit reader), a control plane (Identity, Gateway control routes, governance requests) that cannot read content, and an operations plane (Ops API, operator console, KeyGuard) on a separate ingress and identity provider.
2. THE Platform SHALL run `frontend` (3000), `gateway` (8000), `ingestion` (8001), `retrieval` (8002), `generation` (8003), `citation_validator` (8004), `identity` (8005), `ops` (8006) and `audit` (8007) as separate deployables, each with its own Docker image and database role, holding only the credentials listed in §4.2 and doing none of the "must never" actions listed there.
3. THE Platform SHALL run the workers and jobs `ingestion-worker`, `indexer`, `reconciler`, `identity-worker`, `audit-anchor` (hourly) and `retention`.
4. THE Platform SHALL have every service write audit events through `audit_append` with a payload sealed to a public key, and only the Audit_Service SHALL hold a key that reads audit payloads.
5. THE Platform SHALL scale retrieval and inference horizontally, independently of the stateless API and UI layers.
6. THE Platform SHALL run the same code paths locally and in production, with only adapters differing.
7. THE Platform SHALL enforce the boundaries of the §4.3 table: browser to presentation tier carries only an opaque session ID; presentation tier to Gateway carries the Auth0 access token, never forwarded; Gateway to services carries a one-audience 60-second Context_Token plus the caller's service credential; services to stores use scoped roles, read-only versus read-write vector keys, per-service ACLs and KMS grants.

**Status:** Partial

**Evidence:** The nine service packages exist under `services/` and `frontend/` with their own `pyproject.toml`, and a shared `infra/docker/service.Dockerfile` and `frontend/Dockerfile` exist. The MVP runs all Python services inside one Gateway process (`services/gateway/src/gateway/app.py`, `Services`), except `ops` (`make ops`) and the workers started by `make workers` (`tools/dev.py --workers`) (DEV-01). Criterion 3: `identity.worker`, `audit.worker` and `ingestion.production worker|indexer|reconciler` entry points exist; no `retention` worker was found (retention runs inside `destruction.Lifecycle`). Criteria 4, 5 and 7 are not met in the MVP (DEV-01, DEV-12, DEV-13, DEV-18). Criterion 6 is the stated aim of `docs/production.md` (additive schema, flags).

### Requirement 84: Allowed calls and import boundaries

**ID:** R-84 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §4.7 · **Gates:** G0.5, G0.11, G5.2

**User Story:** As a security reviewer, I want network reachability and code imports restricted by rule and checked in CI, so that a service cannot reach stores or libraries it must never use.

#### Acceptance Criteria

1. THE Platform SHALL let the browser reach only the Frontend; only the Frontend reach the Gateway (and its own session-store Valkey user); only the Gateway reach internal services; only `retrieval` (read-only) and `ingestion` (read-write) reach Qdrant; only `ingestion` and its workers reach the object store; only `identity` reach the Auth0 Management API; and only `ops` be exposed on the operator ingress.
2. THE Toolchain SHALL enforce with import-linter: no service imports another service's package; `gateway` imports no `lmqa_vectorstore`, `lmqa_objectstore`, chunk models or `lmqa_keys` decrypt functions; `retrieval` imports no `lmqa_objectstore` or LLM client; `citation_validator` imports no LLM client, `lmqa_vectorstore` or `lmqa_objectstore`; `identity` imports no chunk, document-content or audit-payload models; only `lmqa_vectorstore` holds a Qdrant client.
3. THE Toolchain SHALL ban `sqlalchemy.create_engine` and `psycopg.connect` outside `lmqa_db` with ruff TID251.
4. THE Toolchain SHALL fail when a deliberately violating fixture package is added (negative control).
5. THE Toolchain SHALL enforce with an ESLint restricted-imports rule that the Frontend calls the Gateway only through the generated client.

**Status:** Partial

**Evidence:** Criteria 2 (with an MVP exception), 3 and 4 are met: `pyproject.toml` (`[tool.importlinter]` contracts; `banned-api` for `sqlalchemy.create_engine` and `psycopg.connect`; `libs/lmqa_db/**` exempt), `tests/controls/lmqa_control_violation/`, `tests/contract/test_stage0_toolchain.py::test_control_violating_package_breaks_a_contract`; `docs/production.md` reports "lint-imports 7 contracts kept". The independence contract exempts `gateway` because it composes the services (DEV-01), and the validator contract forbids importing `generation`, yet the MVP runs LLM entailment from the Gateway's query flow (DEV-05). Criterion 1: `compose.yaml` binds every port to 127.0.0.1 but defines no networks. Criterion 5 was not found in `frontend/eslint.config.mjs`.

### Requirement 85: Technology stack, adoption policy, supply chain and observability

**ID:** R-85 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §4.5, D18 to D22, DEF-32 · **Gates:** G0.1, G0.4, G10.7, G10.9

**User Story:** As an engineer, I want the stack pinned and recorded, upgrades governed by an adoption policy, artifacts signed and services observable, so that builds are reproducible and supply-chain risk is controlled.

#### Acceptance Criteria

1. THE Platform SHALL use the §4.5 stack: Python 3.14 with `uv`, `ruff`, `pytest`, `pyright` (blocking, strict on `libs/`); FastAPI and Pydantic v2 only; SQLAlchemy 2 async, `psycopg` 3 and Alembic through `lmqa_db`; PostgreSQL 18 through PgBouncer (1.21 or later); Qdrant with the client pinned to the server minor; Valkey; Procrastinate (Celery 5.6 fallback per G0.13); S3 and SeaweedFS; Next.js 16, React 19, Node 24 LTS; `@auth0/nextjs-auth0` v4; Tailwind CSS 4 with shadcn/ui; OpenTofu; AWS KMS and OpenBao; ClamAV; OpenTelemetry with Grafana, Loki, Tempo and Prometheus; k6 and Playwright.
2. THE Toolchain SHALL treat `uv.lock`, `pnpm-lock.yaml` and container image digests as the authority, record resolved versions in `docs/versions.md`, and fail G0.1 on drift.
3. THE Platform SHALL adopt a new major runtime or database version only after general availability, its first patch release, driver and wheel availability and a full cumulative gate run; SHALL apply critical security fixes within 72 hours and high within 7 days; and SHALL hold other dependency updates for a 7 to 14 day cooldown.
4. THE Platform SHALL pin container images by digest and use non-root, minimal base images.
5. THE Toolchain SHALL produce a CycloneDX SBOM, sign images with cosign keyless signing, publish GitHub artifact attestations, scan with Trivy, Grype and Semgrep, verify the release attestations of `ruff` and `uv`, and verify provenance at deploy.
6. THE Platform SHALL emit OpenTelemetry traces with `org_id` and `workspace_id` as span attributes and never content.
7. THE Platform SHALL avoid AGPL parsers in the commercial product.

**Status:** Partial

**Evidence:** Criterion 2 is met: `docs/versions.md` from `tools/gen_versions.py`, `tests/contract/test_stage0_toolchain.py::test_version_ledger_equals_the_lockfiles`. Criterion 4 is mostly met: `compose.yaml` pins every default image by digest; the `observability` image is `grafana/otel-lgtm:latest` without a digest (DEV-44). Criterion 7 is met: `services/ingestion/src/ingestion/ocr.py` uses `pypdfium2` and avoids PyMuPDF. Criterion 1 is partly met (see the Technology landscape table; SQLAlchemy and Alembic are not used, migrations are SQL files applied by `libs/lmqa_db/src/lmqa_db/migrate.py`; no shadcn/ui, k6, Playwright or OpenTelemetry instrumentation). Criterion 3: `docs/versions.md` states the policy for newer versions; no cooldown automation exists. Criteria 5 and 6 were not found beyond a cosign mention in `tools/gatekeeper.py`.

### Requirement 86: Environments and the dependency doctor

**ID:** R-86 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §4.6, §2.3 local-host first · **Gates:** G0.9

**User Story:** As an engineer, I want each environment to use real dependencies as §4.6 lists and a doctor that proves they work before tests run, so that "local" never means "fake".

#### Acceptance Criteria

1. THE Platform SHALL use per environment: Auth0 `dev`, `ci`, `staging`, `prod` tenants (prod with BAA where PHI is processed); operator tenants `platform-staging` and `platform-prod`; KMS in AWS dev, CI (OIDC federation, no static keys), staging and production accounts plus a vault account; a real Object Lock anchor bucket in every environment; Compose containers locally and service containers in CI for PostgreSQL, Valkey and Qdrant; SeaweedFS locally and in CI and S3 in staging and production; real LLM and embedding providers with spend caps; public real corpus outside production; a real mailbox read over IMAP.
2. WHEN `make doctor` runs, THE Doctor SHALL verify every real dependency (credentials present, reachable, budgets set) and print what is missing without printing secret values.
3. THE Doctor SHALL verify KMS create, encrypt, decrypt, disable and enable; Object Lock write succeeds and delete is refused; one real LLM call within budget; IMAP read; embedding and re-ranker models load and process a real chunk; ClamAV signatures are current.

**Status:** Partial

**Evidence:** Criterion 2 is met: `tools/doctor.py` (`check_settings`, `check_database`, `check_auth0`, `check_models`, `check_keys`, `check_reranker`, `check_infrastructure`, `check_external`; "prints names, never values" per `Makefile`). Criterion 1 is partly met: Compose services in `compose.yaml`; `infra/aws/main.tf` defines a CI OIDC role (`aws_iam_openid_connect_provider.github`, `aws_iam_role.ci`). Criterion 3 was not verified check by check; `docs/production.md` lists the AWS account, Object Lock buckets, mailbox and on-call webhook as missing external prerequisites. Managed or Helm-deployed stores for staging and production are deferred with Kubernetes.

### Requirement 87: Cross-component compatibility handling

**ID:** R-87 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §4.8, DEF-52, DEF-53, DEF-58, DEF-61, DEF-62 · **Gates:** G0.4, G0.13, G1.3, G1.7, G3.5, G8.4

**User Story:** As an engineer, I want every known cross-component constraint handled and proven by its gate, so that components that work alone also work together.

#### Acceptance Criteria

1. THE Platform SHALL apply each handling listed in the §4.8 table: request path through the pooler with prepared statements configured and workers and migrations on direct connections; `NULLIF(current_setting(...), '')` in every policy; `proxy.ts` only and the client type fixed in OpenTofu; a server-side session store; accepted dynamic rendering for nonce CSP; a filtering wrapper with read-only and read-write Qdrant keys and a collection-per-workspace tier; the Qdrant client pinned to the server minor; application-level object encryption with Object Lock exercised on real S3; OpenBao for immediate-shred tests and real KMS for schedule, cancel and policy tests; hour-long signer certificates; a wheel check at lock time with model-serving images allowed to pin Python 3.13; an explicit ruff rule list with `docs/` excluded from format checks; Pydantic v2 only with `pydantic.v1` banned; Chromium-only authentication flows; a contract test pinning Auth0 method names; upload helper headers and CORS as code for checksummed presigned PUT; `text/event-stream` excluded from buffering and compression; an RFC 9180 HPKE library with cross-implementation test vectors; smoke and revocation tests run against Valkey itself; Mermaid diagrams parsed in CI.
2. THE Toolchain SHALL run, for each constraint, the gate the §4.8 table names.

**Status:** Partial

**Evidence:** Met handlings: PgBouncer transaction pooling and prepared statements (`tests/integration/test_stage0_infra.py`), transactional defer on direct worker connections (`tests/integration/test_stage0_queue_spike.py`), `NULLIF` context reads (`db/policies/10_helpers.sql`), `proxy.ts` (`frontend/src/proxy.ts`), the Regular Web Application client in `infra/auth0/main.tf`, `pydantic.v1` banned (`pyproject.toml`), `Cache-Control: no-transform` and `X-Accel-Buffering: no` on the stream (`services/gateway/src/gateway/production.py`), Valkey ACL and pub/sub tests (`test_valkey_pubsub_channels_are_scoped`), and the Qdrant client pinned to the server minor (`qdrant-client>=1.20,<1.21` in `pyproject.toml` against server 1.20.0 in `compose.yaml`). Coded but unproven: server-side sessions, Qdrant wrapper, application-level encryption, OpenBao shredding, signer certificates, HPKE sealing (no cross-implementation vectors found). Not found: upload CORS as code, Mermaid parsing in CI, Chromium WebAuthn tests, a wheel check at lock time.

### Requirement 88: Repository structure, contracts and documentation

**ID:** R-88 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §18, §3.3, §24 ADR list · **Gates:** G0.10, G0.12

**User Story:** As an engineer, I want the monorepo laid out as §18 describes with contracts as a first-class directory and the ADRs and runbooks present, so that tooling, tests and reviewers share one source of truth.

#### Acceptance Criteria

1. THE Platform SHALL use a `uv` workspace with one lockfile, `src/` layout per package, small `lmqa_*` libraries (`lmqa_models`, `lmqa_auth`, `lmqa_db`, `lmqa_keys`, `lmqa_security`, `lmqa_vectorstore`, `lmqa_objectstore`, `lmqa_audit`, `lmqa_logging`, `lmqa_telemetry`, `lmqa_testing`) and one directory per service under `services/`, each with `src/`, `tests/`, `Dockerfile` and `pyproject.toml`.
2. THE Platform SHALL keep `contracts/` with `openapi/` (gateway, identity, ingestion, retrieval, generation, citation-validator, audit, ops), `authz-matrix.yaml`, `features.toml`, `state-machines.yaml`, `claims/` and `events/` (audit, outbox and ledger JSON Schemas), and THE Toolchain SHALL lint OpenAPI with zero errors, compile the generated TypeScript client and validate `authz-matrix.yaml` and `state-machines.yaml` against their schemas.
3. THE Platform SHALL keep `db/` (migrations, reviewed policies, roles), `prompts/`, `eval/`, `corpus/`, `infra/` (compose, auth0, keyguard, aws), `tools/` (gatekeeper, doctor, load_corpus, leakscan, state_machine_gen, auth_harness, mvp_report) and `tests/` (e2e, isolation, contract, load, chaos, `controls.md`).
4. THE Platform SHALL keep `docs/architecture.md`, `docs/versions.md`, `docs/compliance/`, `docs/diagrams/`, ADRs 0001 to 0012 and the runbooks `leaked-code`, `suspended-admin`, `org-recovery`, `key-deletion-alert`, `ingestion-stuck`, `citation-validation-failing` and `restore-and-shred`.
5. THE Platform SHALL keep `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS` (security review on `db/policies/`, `contracts/authz-matrix.yaml`, `contracts/state-machines.yaml`, `libs/lmqa_keys/`, `libs/lmqa_auth/`, `infra/keyguard/`, `infra/auth0/`), `stages.toml`, `STAGE`, `Makefile` (`up`, `doctor`, `gate`, `isolation`, `load-corpus`, `eval`), `compose.yaml`, `compose.override.yaml`, `compose.test.yaml` and `.env.example`.
6. THE Toolchain SHALL render every Mermaid diagram in CI and pass a link check.
7. THE Platform SHALL use the §3.3 rename map: `Organization` instead of a `Tenant` model, `org_id` and `workspace_id` instead of `tenant_id`, and `tools/load_corpus` through the real onboarding API instead of a demo-tenant seed script.

**Status:** Partial

**Evidence:** Criterion 1 is mostly met: `pyproject.toml` (`[tool.uv.workspace] members = ["libs/*", "services/*"]`), `uv.lock`, nine libraries without `lmqa_logging` and `lmqa_telemetry`, services without per-service `tests/` or `Dockerfile` (a shared `infra/docker/service.Dockerfile`). Criterion 2 is partly met: `contracts/openapi/gateway.json` only, `contracts/schemas/*.schema.json`, `contracts/claims/auth-methods.json`, no `events/`; `tests/contract/test_stage0_toolchain.py` validates schemas and the generated client. Criterion 4 is mostly met: `docs/adr/0001` to `0012`, all seven runbooks (5 to 7 lines each), `docs/versions.md`; no `architecture.md`, `compliance/` or `diagrams/`. Criterion 5 is partly met: no `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, `compose.override.yaml` or `compose.test.yaml`; the Makefile has no `isolation` target. Criterion 6 is partly met: `test_relative_links_in_docs_resolve`; no Mermaid check. Criterion 7 is met in schema naming (`organizations`, `org_id`, `workspace_id`) and `tools/load_corpus.py`.

### Requirement 89: Real-data and no-mocks rules

**ID:** R-89 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §2.3, §2.4 A4, §19.1, §19.3 banned API, §22 (R8), DEF-10, D27, D28 · **Gates:** G0.8, G0.11

**User Story:** As a reviewer of test evidence, I want every test to use real documents, real systems and real accounts, so that a passing gate means the real system works.

#### Acceptance Criteria

1. THE Test_Suite SHALL use only fixtures from the corpus manifest and SHALL contain no generated text, lorem ipsum or invented contracts or charts.
2. THE Test_Suite SHALL use no mocks, fakes, stubs or in-memory substitutes for PostgreSQL, Qdrant, Valkey, the object store, KMS, Auth0, the LLM, the embedding, re-ranking and entailment models, or SMTP and IMAP, and THE Toolchain SHALL ban `unittest.mock`, `pytest_mock`, `respx`, `responses`, `faker`, `factory` and `freezegun` with ruff TID251.
3. THE Platform SHALL keep customer data, real PHI, client files and privileged material out of dev, CI and staging, and SHALL run credentialed datasets only in an opt-in lane with self-hosted models.
4. THE Test_Suite SHALL use real Auth0 identities with project-owned mailboxes and load data through the product's onboarding and upload APIs, never through SQL inserts.
5. THE Test_Suite SHALL list every negative control (EICAR, planted secrets, crafted JWTs, adversarial prompts, XSS strings, injected faults) in `tests/controls.md` and mark it `control`.
6. THE Platform SHALL accelerate time only through configuration values, and a lint test SHALL fail if the production profile is below policy minimums.
7. THE load tests SHALL scale by replicating real documents and never synthesize text.

**Status:** Partial

**Evidence:** Criterion 2's ban list is met in `pyproject.toml` and proven by `test_control_banned_import_fails_ruff` and `test_no_fake_data_or_mocking_packages_in_the_lockfile` (`tests/contract/test_stage0_toolchain.py`). Criterion 5 is met: `tests/controls.md` (C-IMPORT, C-MOCK, C-SECRET, C-RLS-OFF). Criterion 6 is coded in `libs/lmqa_models/src/lmqa_models/policy.py` (`lint_production`). Criterion 1 is partly met: `corpus/manifest.toml` with SHA-256, but `IPC.pdf` and `tests/questions.json` are outside the manifest (DEV-42). Criterion 4 is not met: `make demo` and `make demo-web` simulate Auth0 logins with locally signed tokens (DEV-35); `tools/load_corpus.py` calls `create_ingestion` and the database directly instead of the HTTP onboarding and upload APIs. Criteria 3 and 7 were not verifiable in code. The ten rules R1 to R10 appear as a table only in the split file (open question Q-01).

### Requirement 90: Test taxonomy and pytest configuration

**ID:** R-90 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §19.2, §19.4 · **Gates:** G0.2, all stage gates

**User Story:** As an engineer, I want every test classified by kind and stage and run under strict pytest settings, so that gate runs are exact and flaky tests are fixed instead of retried.

#### Acceptance Criteria

1. THE Test_Suite SHALL use the markers `unit`, `integration`, `contract`, `live_auth0`, `live_kms`, `live_llm`, `e2e`, `isolation`, `perf`, `chaos`, `control` and `stage0` to `stage11`, and SHALL give every test exactly one stage marker and one of `unit`, `integration`, `contract`, `e2e`.
2. THE Test_Suite SHALL run in random order (`pytest-randomly`) and in parallel (`pytest-xdist`) where fixtures allow.
3. THE Test_Suite SHALL configure `minversion = "9.1"`, `--strict-markers`, `--strict-config`, `--import-mode=importlib`, `xfail_strict = true`, `asyncio_mode = "strict"`, `timeout = 180` and `filterwarnings = ["error"]`, and SHALL install no rerun plugin.
4. THE Test_Suite SHALL run each lane as §19.2 assigns: unit, integration and contract on every push; live subsets on every pull request and full live lanes nightly; isolation as a required check on every merge; perf and chaos nightly and at the Stage 10 gate.

**Status:** Partial

**Evidence:** Criteria 1 and 3 are mostly met: `pyproject.toml` (`[tool.pytest.ini_options]` with all markers, strict flags, `xfail_strict`, `timeout = 180`, `filterwarnings = ["error"]`; no `asyncio_mode`, and `pytest-asyncio` is not a dependency) and `conftest.py` (marker enforcement per the comment in `pyproject.toml`). Criterion 2 is partly met: `pytest-randomly` and `pytest-xdist` are dependencies, but the gate runs with `-p no:randomly` (`stages.toml`). Criterion 4 is not met: no CI workflow runs tests (`.github/workflows/secret-scan.yml` only).

### Requirement 91: ruff configuration

**ID:** R-91 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** §19.3 · **Gates:** G0.2, G0.11

**User Story:** As an engineer, I want an explicit, maximal ruff rule set recorded by hash, so that upgrades never change the gate silently.

#### Acceptance Criteria

1. THE Toolchain SHALL configure ruff with `target-version = "py314"`, `line-length = 100`, `select = ["ALL"]`, the ignore list of §19.3, the Google docstring convention, the §19.3 banned-API list and the §19.3 per-file ignores.
2. THE Toolchain SHALL run `ruff format --check` and `ruff check` with no `--fix` and fail on any finding and on any unused suppression comment.
3. THE Gatekeeper SHALL record the ruff config hash in every gate attestation.

**Status:** Partial

**Evidence:** Criterion 2 is met: `stages.toml` gate steps `ruff format --check` and `ruff check --no-fix`; `docs/production.md` reports both clean. Criterion 3 is met: `tools/gatekeeper.py` (`ruff_config_hash`). Criterion 1 is partly met: `pyproject.toml` has `target-version = "py314"` and the banned-API list, but `line-length = 120` and `select = ["E", "F", "W", "I", "B", "UP", "S", "SIM", "RUF", "TID"]`; `docs/production.md` reports about 1,700 findings under `select = ["ALL"]` at line length 100 (DEV-33).

### Requirement 92: Coverage and mutation thresholds

**ID:** R-92 · **Type:** NFR · **Priority:** P1 · **Persona:** Engineer · **Design:** §19.5 · **Gates:** G7.1, all stage gates

**User Story:** As a reviewer, I want coverage and mutation floors enforced, highest on security-critical code, so that tests demonstrably exercise what they claim to.

#### Acceptance Criteria

1. THE Toolchain SHALL require 90 percent line and 85 percent branch coverage on all Python packages.
2. THE Toolchain SHALL require 95 percent line and 90 percent branch coverage on `lmqa_auth`, `lmqa_keys`, `lmqa_security`, `lmqa_db`, `services/identity` and the `services/gateway` auth modules, and a mutation score of at least 75 percent on `lmqa_security` and `lmqa_keys`.
3. THE Toolchain SHALL require 95 percent line coverage, 90 percent branch coverage and an 80 percent mutation score on `services/citation_validator`.
4. THE Test_Suite SHALL unit-test every pure frontend helper and cover every route of the route matrix end to end.

**Status:** Not started

**Evidence:** `pyproject.toml` enables branch coverage (`[tool.coverage.run] branch = true`) with no `fail_under` and no per-package thresholds; no mutation tool is a dependency; no frontend unit or end-to-end tests were found.

### Requirement 93: Gate mechanics, gatekeeper, profiles and feature flags

**ID:** R-93 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer, gatekeeper · **Design:** §1.4, §19.6, §19.7, DEF-31, DEF-46 · **Gates:** all

**User Story:** As a delivery lead, I want gates to run the same steps every time, be cumulative and be the only way to advance a stage or enable a feature, so that "done" is mechanical.

#### Acceptance Criteria

1. WHEN `make gate STAGE=n` runs, THE Gatekeeper SHALL run in order `uv sync --frozen`, `ruff format --check`, `ruff check`, `pyright`, frontend lint and type check, import-linter, contract linting, gitleaks, `pip-audit` and `pnpm audit`, `pytest -m "stage0 or … or stage{n}"` with coverage and the stage's special suites, and SHALL write `gates/stage-{n}.json` with commit SHA, tool versions, ruff config hash, test counts by marker, coverage, live-lane counts, durations and the verdict.
2. WHEN a gate runs in CI, THE Toolchain SHALL sign the attestation with cosign keyless signing and publish it for that commit.
3. IF a pull request modifies paths owned by a stage above `STAGE + 1`, THEN THE Gatekeeper SHALL reject it.
4. THE Gatekeeper SHALL advance `STAGE` to `n + 1` only through a commit that requires a valid signed attestation for stage `n` on the exact commit, with no skips outside a listed set of platform markers and a non-zero live-lane count where the stage requires one.
5. THE Gatekeeper SHALL re-run all gates from stage 0 to the current stage on every pull request.
6. THE Gatekeeper SHALL define gate profiles in `stages.toml`, with `full` as default and the only profile valid for production, and SHALL allow a profile to reduce sizes and feature scope but never a safety threshold.
7. THE Gatekeeper SHALL allow a feature flag in `contracts/features.toml` to be enabled only with signed attestations from its bound gates, and a disabled feature's endpoints SHALL answer 404.
8. THE Gatekeeper SHALL mark a stage done only when every gate check passes on a clean CI run twice in a row with zero skipped checks and zero waivers, and SHALL list items that do not gate the stage as "deferred" in the stage's table only.
9. IF a gate check fails, THEN THE engineering process SHALL stop the line, add a failing test that reproduces the defect, fix the cause, keep the regression test and re-run the cumulative gate, and IF the failure is in an isolation, authentication, key or audit check, THEN THE process SHALL record an incident review as an ADR addendum.

**Status:** Partial

**Evidence:** Criteria 1, 3, 4, 5, 6 and 7 are coded in `tools/gatekeeper.py` (`run_gate`, `check_paths`, `advance`, `valid_attestation`, `check_features`) and `stages.toml` (`[stage.n] owns`, `[[gate.step]]`, `[profile.full]`, `[profile.mvp]` skipping `pyright`, `pip-audit` and `pnpm audit`, `[live]`), with `make gate`, `make advance` and `make paths` in the `Makefile`; `test_gatekeeper_refuses_to_advance_without_an_attestation` exists. Criterion 2 is not met: no CI workflow runs the gate (the gatekeeper docstring says CI signs; no workflow exists). Criterion 8's "twice in a row" rule and criterion 9 were not found. The repository is at `STAGE = 0` while code for Stages 1 to 9 exists, which rule 1 would reject (DEV-43).

### Requirement 94: Staged delivery and stage gates

**ID:** R-94 · **Type:** NFR · **Priority:** P0 · **Persona:** Delivery lead · **Design:** §1.4, §20 (Stage 0 to Stage 11) · **Gates:** G0.1 to G11.10

**User Story:** As a delivery lead, I want the system built in the twelve stages of §20 with every gate row passing before the next stage, so that each guarantee is proven before anything depends on it.

#### Acceptance Criteria

1. THE Platform SHALL deliver Stage 0 (Foundation and real dependencies) through Stage 11 (Production readiness) in order, each building what §20 lists for it.
2. THE Gatekeeper SHALL treat every gate row of a stage's table (G0.1 to G0.13, G1.1 to G1.12, G2.1 to G2.12, G3.1 to G3.10, G4.1 to G4.12, G5.1 to G5.12, G6.1 to G6.10, G7.1 to G7.12, G8.1 to G8.10, G9.1 to G9.12, G10.1 to G10.10, G11.1 to G11.10) as a check whose pass criterion must hold before the next stage begins.
3. THE Eval_Harness SHALL record numeric floors for retrieval and validation quality in `eval/floors.toml` from the Stage 4 and 5 baselines, and THE process SHALL lower a floor only through an ADR.
4. WHERE a gate check depends on Kubernetes (production overlays and Kubernetes network policies in Stage 11), THE Platform SHALL treat that part as deferred by the user until Kubernetes is added.

**Status:** Partial

**Evidence:** `STAGE` is `0`. Stage 0 checks have tests: G0.1, G0.4, G0.5, G0.6, G0.10, G0.11, G0.12 (ADRs and links) and G0.13 in `tests/contract/test_stage0_toolchain.py`, `tests/integration/test_stage0_infra.py` and `tests/integration/test_stage0_queue_spike.py`; `docs/production.md` records 22 + 4 passes and a 27-pass, 2-fail contract run not re-run. No tests exist for Stages 1 to 11 (`tests/` holds `contract/`, `integration/`, `controls/` and MVP leftovers). G0.2 fails under the design's ruff rule set (R-91), G0.3 is skipped (R-85), G0.7 lacks Playwright, G0.8 lacks the corpus minimums (R-98) and G0.9 lacks the external accounts (R-86). `eval/floors.toml` is marked "BASELINE" on unreviewed labels.

### Requirement 95: Isolation and verification suite

**ID:** R-95 · **Type:** NFR · **Priority:** P2 · **Persona:** Security reviewer · **Design:** §21 · **Gates:** G10.2, G10.3

**User Story:** As a security reviewer, I want a merge-blocking suite that tries every cross-scope access from every wrong position and scans every output channel for foreign provenance, so that isolation is proven continuously.

#### Acceptance Criteria

1. THE Test_Suite SHALL build two organizations, each with two admins and two tenants and a distinct real corpus per workspace, through the product's own flows.
2. THE Test_Suite SHALL scan every response, SSE frame, ledger row, cache entry, log line, audit export, object URL and error body of every wrong-position caller for any identifier or distinctive content hash from another scope, and IF any is found, THEN THE Toolchain SHALL fail the build.
3. THE Test_Suite SHALL assert every group in the §21 table: admin to admin, Super Admin boundary, tenant to tenant, cross-organization, fail closed, token abuse, revocation, codes, escalation, walls, emergency and break-glass, cache, async, index consistency, audit, gated release, noisy neighbor, private documents, onboarding tokens, aggregates, successor transfer, key shredding, key guardrails, operators and contract.
4. THE Toolchain SHALL run the suite (`isolation` marker) as a required check on every merge.
5. THE Test_Suite SHALL run a periodic fuzz job that mutates IDs, headers and bodies against every endpoint with each role's token and expects 200 only for in-scope calls and 404 or 403 otherwise.

**Status:** Not started

**Evidence:** No `tests/isolation/` directory exists. `make demo` (`tools/demo.py`) performs 94 scripted checks including RLS isolation and audit tamper detection per `README.md`, but it is a demo script outside `pytest`, uses simulated Auth0 tokens and is not a merge gate.

### Requirement 96: Performance and capacity budgets

**ID:** R-96 · **Type:** NFR · **Priority:** P2 · **Persona:** Engineer · **Design:** §22, §13.3 shard option · **Gates:** G1.4 extension, G1.10, G3.5, G4.12, G5.9, G7.12, G9.10, G10.4, G10.8

**User Story:** As an engineering lead, I want each known performance risk turned into a measured budget, so that scale claims are evidence, not assertions.

#### Acceptance Criteria

1. THE Retrieval_Service SHALL keep retrieval-stage p95 ≤ 800 ms for a tenant with 5,000 grants at 1,000,000 chunks in the workspace, with inline filters up to 256 matters.
2. THE Database SHALL keep RLS policy overhead ≤ 20 percent over an unconstrained baseline at 10,000 grants per user.
3. THE Key_Ring SHALL keep KMS use ≤ 5 percent of the regional quota at peak with a 15-minute workspace key cache.
4. THE Gateway SHALL mint Context_Tokens at p99 ≤ 5 ms with about one KMS signing call per instance per hour.
5. THE Database SHALL sustain 200 audit writes per second per workspace chain.
6. THE Platform SHALL reach the first verified sentence within 6 seconds at p95, with validator time per sentence ≤ 150 ms at p95 on CPU.
7. THE Ingestion_Service SHALL complete a 200-page scanned PDF within 10 minutes at p95 on the reference worker.
8. THE Platform SHALL meet RPO ≤ 5 minutes and RTO ≤ 4 hours for the data plane.
9. THE Test_Suite SHALL measure the budgets at the Stage 10 target scale of 100 organizations × 5 workspaces × 20 tenants and 50 million chunks built by replicating real documents, record results in `docs/perf-report.md`, and change any budget only through an ADR.

**Status:** Not started

**Evidence:** No load tests, k6 profiles or `docs/perf-report.md` exist. Only the Stage 0 queue throughput floor is tested (`tests/integration/test_stage0_queue_spike.py::test_throughput_meets_the_floor`), which belongs to G0.13.

### Requirement 97: Recurring controls and external validation

**ID:** R-97 · **Type:** NFR · **Priority:** P2 · **Persona:** External reviewers, delivery lead · **Design:** §1.5, §25.1, §25.2, §25.3, Stage 11 gates G11.1 to G11.10 · **Gates:** G10.10, G11.1 to G11.10

**User Story:** As a delivery lead, I want the external reviews, agreements, drills and recurring attestations completed and tracked as evidence, so that go-live depends on independent confirmation.

#### Acceptance Criteria

1. THE Platform SHALL run a quarterly access attestation in which each admin reviews tenants, the Super Admin reviews admins and operators review their own access, and SHALL flag unattested accounts.
2. THE Platform SHALL complete an annual external penetration test with no open critical or high findings and medium findings triaged with dates.
3. THE Platform SHALL complete a security architect review with findings closed or accepted by a named owner.
4. THE Platform SHALL obtain counsel sign-off on HIPAA, privilege and ethical-wall rules, retention and breach notification before customer data is processed.
5. THE Platform SHALL execute the Auth0 BAA (plan and add-on), BAAs or no-retention terms for LLM, embedding, OCR and hosting providers and data processing terms.
6. THE Platform SHALL pass disaster-recovery and restore-and-shred drills in a production-like environment and an annual restore-and-shred drill thereafter.
7. THE Platform SHALL prove a generation canary that rolls back on a drop in live citation-validation pass rate.
8. THE Platform SHALL complete operator readiness: on-call rota, drilled runbooks, operator background checks and training and a first access review.
9. THE Platform SHALL admit real customer data only for a pilot customer under a signed BAA with data minimization and agreed success criteria, after counsel sign-off and vendor agreements.
10. THE Platform SHALL complete a go-live checklist signed by named owners for security, privacy, engineering and operations, with a clean `tofu plan` and a passing production-profile policy lint.
11. THE Platform SHALL prepare a review package with architecture, data-flow diagrams, test accounts and the counsel question list.

**Status:** Not started

**Evidence:** No review package, attestation process, agreements or drill records exist in the repository; `docs/production.md` lists these as external prerequisites. The production-profile policy lint in criterion 10 is coded in `libs/lmqa_models/src/lmqa_models/policy.py` (`lint_production`), which is not enough for this requirement.

### Requirement 98: Real-data corpus and evaluation sets

**ID:** R-98 · **Type:** DR · **Priority:** P0 · **Persona:** Engineer, evaluator · **Design:** Appendix B, §19.1, §11.3 floors, D27 · **Gates:** G0.8, G5.3, G7.3, G10.6

**User Story:** As an evaluator, I want a licence-checked real corpus and human-labeled evaluation sets of the sizes Appendix B sets, so that every quality floor rests on real, provenance-tracked data.

#### Acceptance Criteria

1. THE Platform SHALL keep `corpus/manifest.toml` as the only fixture source, with `id`, `title`, `source_url`, `license`, `retrieved_at`, `sha256`, `bytes`, `format`, `domain`, `kind`, `pages`, `scanned`, `allowed_use` (`commercial`, `internal_eval_only`, `excluded`) and notes per item.
2. WHEN the corpus is fetched, THE Corpus_Loader SHALL verify every SHA-256 and fail on any mismatch or missing licence.
3. THE Platform SHALL meet the minimums of at least 150 legal and 150 medical documents, at least 30 scanned multi-page PDFs, at least 10 documents of 100 to 200+ pages, and at least 5 JATS, 20 SPL and 20 DOCX items, in English.
4. THE Platform SHALL use non-commercial sets only when marked `internal_eval_only` and never ship them.
5. THE Eval_Harness SHALL use a held-out set of at least 300 sentence–chunk pairs per domain labeled by a qualified attorney or clinician as the final authority for validator calibration, and evaluation labels SHALL come from published datasets or qualified reviewers, never from the model under test.
6. THE Platform SHALL refresh the corpus quarterly through a manifest change reviewed like code.

**Status:** Partial

**Evidence:** Criteria 1 and 2 are met: `corpus/manifest.toml` (12 items with URL, licence and SHA-256) and `corpus/fetchers.py` (`make corpus` verifies every SHA-256 per `Makefile`). Criterion 3 is not met: 12 items, 6 legal and 6 medical (DEV-37). Criterion 5 is not met: `eval/sets/corpus.toml` labels are marked as needing human review (`eval/floors.toml`). Criteria 4 and 6 were not verified.

### Requirement 99: Configuration catalog and production policy minimums

**ID:** R-99 · **Type:** NFR · **Priority:** P0 · **Persona:** Engineer · **Design:** Appendix C, §19.1 (R7) · **Gates:** G2.10, G11.1

**User Story:** As an operator of the platform, I want every configuration name documented without secrets and the production profile linted against policy minimums, so that a misconfigured deployment fails before it runs.

#### Acceptance Criteria

1. THE Platform SHALL document every variable in `.env.example` without secret values, using the Appendix C groups: Auth0 (`AUTH0_DOMAIN`, `AUTH0_AUDIENCE_MAIN`, `AUTH0_AUDIENCE_ONBOARDING`, `AUTH0_CLIENT_ID_BFF`, `AUTH0_CLIENT_SECRET_BFF`, `AUTH0_M2M_CLIENT_ID`, `AUTH0_M2M_CLIENT_SECRET`, `AUTH0_CLAIMS_NAMESPACE`), database (`PG_DSN_<SERVICE>`, `PGBOUNCER_*`), vector (`QDRANT_URL`, `QDRANT_KEY_RO`, `QDRANT_KEY_RW`), cache (`VALKEY_URL`, `VALKEY_USER_<SERVICE>`), object store (`OBJECT_STORE_ENDPOINT`, `OBJECT_STORE_CREDS_INGESTION`), keys (`KMS_PROVIDER`, `KMS_ORG_KEY_ALIAS_PREFIX`, `KMS_TRUST_ROOT_ID`, `KEYGUARD_*`, `CODE_PEPPER_ID`), models (`LLM_PROVIDER`, `LLM_API_KEY_<ORG>`, `LLM_TEST_BUDGET_USD`, `EMBEDDING_MODEL`, `RERANK_MODEL`, `NLI_MODEL_HASH`), mail (`SMTP_*`, `IMAP_*`) and observability (`OTEL_*`).
2. THE Platform SHALL place M2M variables only in the Identity_Service's environment and pepper material only in the secret manager.
3. THE Toolchain SHALL fail a lint test when the production profile violates any Appendix C minimum: successor transfer, wall lift and private-read waits of at least 72 h, 24 h and 24 h; workspace unseal wait at least 72 h and destroy wait at least 30 days; organization deletion grace at least 30 days and KMS window exactly 30 days for non-drill keys; governance approval expiry at most 72 h; owner recovery wait at least 72 h; step-up age, access-token, context-token and signer-certificate lifetimes at most 300 s, 600 s, 60 s and 3,600 s; privileged idle at most 15 min and absolute at most 8 h; emergency access at most 60 min and at most 5 per user per day; break-glass at most 60 min; operator infrastructure, control-plane and content sessions at most 24 h, 8 h and 4 h; backup retention at most 35 days; MFA always on with SMS and email OTP disabled.

**Status:** Partial

**Evidence:** Criterion 3 is coded in `libs/lmqa_models/src/lmqa_models/policy.py` (`Policy` defaults equal the Appendix C values; `lint_production`), not run in any gate. Criterion 1 is partly met: `.env.example` contains the Auth0, Qdrant, Valkey, object store, KMS (`KMS_PROVIDER`, `KMS_ORG_KEY_ALIAS_PREFIX`, `KMS_TRUST_ROOT_ID`), `CODE_PEPPER_ID`, `LLM_PROVIDER`, `LLM_TEST_BUDGET_USD`, `RERANK_MODEL`, `NLI_MODEL_HASH`, `SMTP_*`, `IMAP_*` and `PGBOUNCER_*` names, and lacks `PG_DSN_<SERVICE>`, `KEYGUARD_*`, `LLM_API_KEY_<ORG>`, `EMBEDDING_MODEL` and `OTEL_*`; `tests/contract/test_stage0_toolchain.py::test_env_example_holds_no_secret_values` checks for secrets. Criterion 2 was not verified.

### Requirement 100: Grounded answers, refusal and disclaimer

**ID:** R-100 · **Type:** FR · **Priority:** P0 · **Persona:** Tenant, Admin · **Design:** §1.1, §2.1 goals 1 and 2, §2.2, §25.1 model error · **Gates:** G6.7, G7.7, G10.6

**User Story:** As a user of a legal or medical answer, I want answers grounded only in my documents, a refusal when they do not answer, and a clear statement that this is not advice, so that I keep human judgment in the loop.

#### Acceptance Criteria

1. THE Platform SHALL ground every answer in retrieved source text and SHALL refuse with the canonical refusal when grounding is insufficient.
2. WHEN unanswerable real evaluation questions are asked, THE Platform SHALL meet the refusal-rate floor, and WHEN answerable ones are asked, THE Platform SHALL keep false refusals at or below the floor.
3. THE Frontend SHALL state with every answer surface that the system reports what the documents say and gives no legal or medical advice.
4. THE Platform SHALL keep a human-review step in the workflow for cited answers.

**Status:** Partial

**Evidence:** Criterion 1 is met in the MVP: the relevance threshold refuses without a model call when nothing passes (`services/retrieval/src/retrieval/service.py`), and the validator replaces fully failing answers with a refusal (`services/citation_validator/src/citation_validator/validator.py`). Criterion 3 is met: `frontend/src/components/chat/chat.tsx` shows "Reports what your documents say. Not legal or medical advice." Criterion 2 is partly met: `eval/floors.toml` has an `abstention = 0.75` floor on unreviewed labels and no false-refusal floor. Criterion 4: the design does not define the human-review workflow (open question Q-11).

## MVP-versus-design deviation register

Every place found where the MVP differs from the v3.1 design. "MVP doc" means the deviation is acknowledged in `docs/mvp.md` (numbered there). Deviations without that mark were found during this review and are not listed in `docs/mvp.md`.

| ID | Design (section) | MVP behavior | Evidence | Requirements affected | Acknowledged |
| --- | --- | --- | --- | --- | --- |
| DEV-01 | Nine separate deployables with own images, roles and credentials (§4.2) | All Python services run inside one Gateway process; only `ops` and the workers run separately | `services/gateway/src/gateway/app.py` (`Services`), `pyproject.toml` independence contract excludes `gateway` | R-31, R-48, R-77, R-83, R-84 | MVP doc #1 |
| DEV-02 | Qdrant behind `lmqa_vectorstore`, pooled collection, RO and RW keys (§10.5, D16) | pgvector in PostgreSQL under RLS; Qdrant path behind disabled `qdrant_vectors` | `db/migrations/0001_schema.sql` (`chunks.embedding vector(768)`), `services/retrieval/src/retrieval/service.py` | R-33, R-35, R-36 | MVP doc #2 |
| DEV-03 | Self-hosted embedding model by default so no document text leaves the boundary (§4.5, §10.5, §11.8) | Gemini embeddings via third-party API; document text sent to Google | `libs/lmqa_vectorstore/src/lmqa_vectorstore/embeddings.py` | R-50 | MVP doc #3 |
| DEV-04 | Identical files, chunks and embeddings never deduplicated or cached across workspaces (§10.8, G4.9) | `embedding_cache` keyed by `(org_id, model, text_sha256)`, shared by every workspace of an organization | `db/migrations/0004_retrieval.sql`, `services/ingestion/src/ingestion/pipeline.py` (`_embed_cached`) | R-1, R-38 | No |
| DEV-05 | V6 by a pinned NLI cross-encoder; Validator calls no generative LLM (§4.7, §11.6) | V6 replaced by a generative LLM entailment pass that can only remove sentences; pinned NLI behind a disabled flag | `services/generation/src/generation/service.py` (`entailment`), `services/gateway/src/gateway/query_flow.py`, `contracts/features.toml` | R-47, R-84 | MVP doc #4 |
| DEV-06 | Checks V1 to V8 only; canonical refusal wording only; model does not produce the citation list (§11.5, §11.6) | Extra checks Q (quote match) and L (lexical support); a "scoped refusal" sentence form; the buffered answer schema asks the model for quotes per citation | `services/citation_validator/src/citation_validator/validator.py` (docstring, `find_quote`, `content_words`) | R-46, R-47 | No |
| DEV-07 | Tags `[chunk_N]`, aliases `chunk_1`, `chunk_2`, … (§9.4, §11.5, V1) | Tags `[S1]`, aliases `S1…Sn` | `prompts/templates/answer_stream.md`, `validator.py` | R-31, R-46, R-47 | No |
| DEV-08 | `sentence_gated` streaming is the default delivery mode; `buffered` only with `regenerate` (§11.6) | Whole answer validated, then returned; streaming behind disabled `sentence_streaming`; `regenerate` not implemented | `services/gateway/src/gateway/query_flow.py`, `services/gateway/src/gateway/stream.py` | R-48 | MVP doc #5 |
| DEV-09 | Column-level AES-256-GCM on titles, chunk text, questions, answers, contact fields; encrypted objects (§12.2, §12.3) | Plaintext columns (`documents.title`, `chunks.text`, `queries.question`, `queries.result`, `users.email`); originals unencrypted on local disk | `db/migrations/0001_schema.sql`, `libs/lmqa_objectstore/src/lmqa_objectstore/__init__.py` | R-39, R-51, R-52, R-58, R-60 | MVP doc #6 |
| DEV-10 | Auth0 Organizations; `main` API organization required; `onboarding` API organization denied (§7.1, §8.2) | One audience; no Auth0 Organizations; BFF client `organization_usage = "allow"`; onboarding routes accept any authenticated token | `libs/lmqa_auth/src/lmqa_auth/verifier.py`, `infra/auth0/main.tf`, `contracts/authz-matrix.yaml` | R-11, R-19, R-71 | MVP doc #7 |
| DEV-11 | Valkey server-side session store with opaque session ID (§8.3, §17.3, D30) | SDK encrypted cookie session by default; Valkey store only with `FEATURE_SERVER_SIDE_SESSIONS=on` | `frontend/src/lib/auth0.ts`, `frontend/src/lib/session-store.ts` | R-20, R-82 | MVP doc #8 |
| DEV-12 | Context tokens on every internal call with real `scope_hash`, `scope_version`, `pv`, `auth_strength`; KMS trust root (§9.1) | Token minted only on the streaming route with `scope_hash=""`, `scope_version=0`, `pv=0`, `auth_strength="unknown"`, verified in-process and discarded; default trust root is a per-process key | `services/gateway/src/gateway/production.py` (`context_for`, `_trust_root`) | R-28, R-83 | MVP doc #9 (partly) |
| DEV-13 | One non-owner `NOBYPASSRLS` role per service; `super_admin` policy set; Gateway limited to `principal_v` (§9.2, §10.3, §16.3) | Two runtime roles: `lmqa_app` (NOBYPASSRLS) and `lmqa_system` (BYPASSRLS) used by identity, onboarding, the Gateway health check, audit and the ingestion worker, with authorization in code | `libs/lmqa_db/src/lmqa_db/database.py`, `db/roles/grants.sql`, `db/policies/15_force_rls.sql` comment | R-3, R-29, R-32, R-79, R-83 | No |
| DEV-14 | Visibility `private` or `matter` only; access rules 1 to 8 (§5.4) | Extra visibility `workspace` (rule 7a) and named shares in `document_shares` (rule 7b); members share with their admin; admins share with chosen members | `db/policies/11_access.sql`, `db/migrations/0003_shares_profiles.sql`, `services/ingestion/src/ingestion/documents.py` | R-4 | MVP doc #10 (partly) |
| DEV-15 | Matters, tiers, walls, emergency access, break-glass (§5.4 to §5.8) | Coded behind disabled `matters_walls_tiers`; MVP uploads carry no matter or tier | `contracts/features.toml`, `services/identity/src/identity/scope_admin.py` | R-5 to R-8 | MVP doc #10 |
| DEV-16 | Provisioning saga; organization `pending` until every step succeeds; workspace `pending → provisioning → active` (§6.3, §6.4, §7.2, §7.3) | Organization inserted `active` directly with an active Super Admin; workspace goes `pending → active` on approval; saga coded but never started | `services/identity/src/identity/service.py` (`create_organization`, `decide_admin`), `services/identity/src/identity/saga.py` | R-10, R-12, R-13 | MVP doc #11 (partly) |
| DEV-17 | Membership states `pending_approval`, `active`, `rejected`, `suspended`, `removed` (§6.2) | MVP machines use `pending` and have no `remove` action; rejecting an admin leaves a `rejected` workspace instead of removing it | `contracts/state-machines.yaml` (`admin_membership`, `tenant_membership`) | R-10, R-13, R-17 | No |
| DEV-18 | One audit chain per workspace plus an organization control chain; audit key per workspace per month; tables partitioned by month (§12.1, §13.3) | One chain per organization; sealed-audit keys per organization per month; no partitioning | `db/policies/30_audit.sql`, `db/policies/31_audit_sealed.sql` (`pg_advisory_xact_lock('audit:' || p_org)`) | R-33, R-51, R-60, R-61 | No |
| DEV-19 | Super Admin governance, co-owner, successor transfer, owner recovery and operator plane (§6.7, §7.5, §7.8, §14) | Coded behind disabled `governance_requests` and `operator_plane`; no co-owner or successor routes; no `owner_recovery` effect registered | `contracts/features.toml`, `services/identity/src/identity/worker.py` (`build`) | R-15, R-18, R-55, R-66 to R-69 | MVP doc #11 |
| DEV-20 | ClamAV, OCR, object store, PgBouncer, Valkey, observability in use (§4.5, §11.1) | Containers exist, but the MVP request path uses none of ClamAV, OCR, object store or Valkey; scanned pages are reported and never embedded | `compose.yaml`, `services/ingestion/src/ingestion/pipeline.py` | R-41, R-42 | MVP doc #12 |
| DEV-21 | Features limited to the design | Additions not in the design: chats (`conversations`) with LLM query planning (standalone follow-ups, up to 3 alternative phrasings sent to an LLM before retrieval), neighbour expansion and near-duplicate removal, user profiles (job title, department, phone), usage counts per member, a public marketing website and role-gated docs under `(site)`, an LLM re-ranker option, multi-key Gemini quota rotation with a local quota counter | `db/migrations/0002_conversations.sql`, `0003_shares_profiles.sql`, `services/gateway/src/gateway/conversations.py`, `services/generation/src/generation/service.py` (`plan_query`), `frontend/src/app/(site)/`, `services/generation/src/generation/rerank.py`, `libs/lmqa_models/src/lmqa_models/quota.py` | R-44, R-80, R-81 | Partly (README, MVP doc) |
| DEV-22 | Two-step presigned upload owned by ingestion into a quarantine prefix; Gateway holds no storage access (§11.1, DEF-23) | Single multipart `POST /v1/documents`; the Gateway process reads the file and the in-process ingestion writes it to local disk | `services/gateway/src/gateway/app.py` (`upload`), `libs/lmqa_objectstore/src/lmqa_objectstore/__init__.py` | R-38, R-41, R-52, R-75 | No |
| DEV-23 | Procrastinate worker with signed envelopes and fair-share slots (§9.3, §10.8) | In-process `Ingestor` thread pool; jobs left `processing` resumed at startup; no envelope | `services/ingestion/src/ingestion/pipeline.py` | R-30, R-38 | No |
| DEV-24 | Document lifecycle `uploading → scanning → parsing → (ocr_review) → indexing → indexed` with side exits (§6.5) | MVP status `processing`, `ready`, `failed`; production `lifecycle` column added by migration 0006 | `db/migrations/0001_schema.sql`, `contracts/state-machines.yaml` (`document`) | R-10, R-41 | No |
| DEV-25 | Token targets 40 / 300 to 700 / 1,200; chunk kinds include clause, SOAP sections, table, footnote (§11.1, §11.2) | Character targets (`TARGET_CHARS = 1600`, `MIN_CHARS = 200`); kinds `preamble`, `section`, `paragraph` | `services/ingestion/src/ingestion/chunker.py`, `db/migrations/0001_schema.sql` | R-41, R-43 | No |
| DEV-26 | API paths of §15 | Different or extra paths: `/v1/queries` (not `/v1/query`), `/v1/onboarding/preview-tenant`, `/v1/workspace/members`, `POST /v1/org/code` for generate and rotate, `/v1/governance`, `/v1/emergency-access`, `/v1/break-glass`, `/v1/reviews`, `/v1/workspace/matters/{id}/grants` and `/walls`, plus `/v1/conversations`, `/v1/profile`, `DELETE /v1/onboarding/request`; many §15 endpoints absent | `contracts/authz-matrix.yaml` | R-2, R-71 to R-76 | No |
| DEV-27 | Rate limits and code-failure limits in Valkey across replicas; per-lookup-ID circuit breaker (§7.6, §13.7) | In-process `SlidingWindow` counters per process; no per-code breaker | `services/identity/src/identity/ratelimit.py`, `services/identity/src/identity/service.py`, `services/gateway/src/gateway/app.py` | R-16, R-64 | No |
| DEV-28 | Privileged sessions 15 min idle / 8 h; tenants 30 min / 12 h (§8.4) | 30 min idle / 8 h absolute for everyone | `frontend/src/lib/auth0.ts` | R-21 | MVP doc #14 |
| DEV-29 | Step-up for code generation and rotation, admin approval and removal, tenant removal, policy changes, governance approvals, exports (§8.7) | Step-up only on flag-gated governance and break-glass routes; code and approval routes have none | `contracts/authz-matrix.yaml` | R-13, R-24, R-72, R-74 | Partly (MVP doc #7) |
| DEV-30 | `azp` checked; `org_id` must equal the active membership's organization; role-claim mismatch denied and alerted (§8.3, §8.5) | `azp` not checked; `org_id` parsed but not compared; `role_claim` parsed but unused | `libs/lmqa_auth/src/lmqa_auth/verifier.py`, `services/gateway/src/gateway/app.py` | R-20, R-22 | No |
| DEV-31 | Provider, keys and budgets per organization; no silent switch to another provider unless the organization configured it; maximum output 1,500 tokens (§10.4, §11.3, §11.8) | Global `LLM_PROVIDER`, `LLM_MODEL` and `LLM_FALLBACK_MODELS` that may mix providers; `llm_max_output_tokens = 8192` | `libs/lmqa_models/src/lmqa_models/settings.py`, `services/generation/src/generation/llm_client.py` | R-33, R-34, R-44, R-50 | No |
| DEV-32 | Token counts from the provider's tokenizer within 1 percent; guarded compression (§11.4) | Token counts estimated; no compression | `services/generation/src/generation/prompts.py` (`estimate_tokens`) | R-45 | No |
| DEV-33 | ruff `select = ["ALL"]`, line length 100; `pyright` blocking; coverage thresholds; `pytest-asyncio`, Schemathesis, Playwright (§4.5, §19.3 to §19.5) | Subset of rule families at line length 120 (about 1,700 findings under the design set); `pyright` skipped by the `mvp` profile; no `fail_under`; those plugins absent | `pyproject.toml`, `stages.toml`, `docs/production.md` | R-85, R-90 to R-92 | Partly (`docs/production.md`) |
| DEV-34 | `eventsource-parser`; client from `openapi-typescript` and `openapi-fetch`; shadcn/ui; Trusted Types; no inline scripts (§4.5, §17.3) | Custom SSE parser; hand-written `fetch` wrapper over generated types; no shadcn/ui; `style-src 'unsafe-inline'`; no Trusted Types | `frontend/src/lib/sse.ts`, `frontend/src/lib/api-client.ts`, `frontend/src/proxy.ts`, `frontend/package.json` | R-82 | No |
| DEV-35 | No mock identity provider anywhere (§8.10, DEF-10) | `make demo` and `make demo-web` sign test tokens with a throwaway local key | `README.md`, `tools/demo.py`, `tools/demo_web.py` | R-27, R-89, R-95 | Yes (README) |
| DEV-36 | CI workflows `ci`, `gates`, `isolation`, `nightly-live`, `security`, `release`; `tofu plan` drift checks (§8.2, §18, §19.6) | Only `secret-scan.yml` (gitleaks); `docs/production.md` says CI/CD was skipped at the owner's request | `.github/workflows/secret-scan.yml`, `docs/production.md` | R-19, R-90, R-93 | Yes (`docs/production.md`) |
| DEV-37 | Corpus minimums 150 legal and 150 medical documents and format quotas (Appendix B, G0.8) | 12 items (6 legal, 6 medical); evaluation labels not human-reviewed | `corpus/manifest.toml`, `eval/floors.toml` | R-94, R-98 | Yes (`docs/production.md`) |
| DEV-38 | Production schema applied and gate-proven (Stage 1) | Migrations 0006 to 0008 never applied to any database | `docs/production.md` | R-4 to R-10, R-78 | Yes |
| DEV-39 | `GET /v1/health` returns liveness only, no detail (§15.7) | Health returns `llm_configured`, `model` and `reranker` | `services/gateway/src/gateway/app.py` (`health`) | R-75 | No |
| DEV-40 | Organization creation captures deployment type and data region (§7.2) | `CreateOrg` takes name and kind only; region defaults to `us-east-1` in migration 0006 | `services/gateway/src/gateway/app.py` (`CreateOrg`), `db/migrations/0006_production_core.sql` | R-12 | No |
| DEV-41 | Auth strength names `passkey`, `webauthn_mfa`, `otp_mfa`, `password` (§8.4) | Names `otp`, `mfa`, `passkey`, `passkey_mfa` | `infra/auth0/actions/post-login.js`, `libs/lmqa_auth/src/lmqa_auth/verifier.py` | R-21 | No |
| DEV-42 | `corpus/manifest.toml` is the only fixture source (§19.1, Appendix B) | Untracked-by-manifest files in the repository root and tests: `IPC.pdf`, `test.txt`, `tests/questions.json`, `tests/run_pipeline.py`, `tests/results/`; `stages.toml` marks them as MVP leftovers | `stages.toml` comment, repository root | R-89 | Yes (`stages.toml`) |
| DEV-43 | Code for stage `n + 2` is rejected; stages advance only by attestation (§19.6) | `STAGE = 0` while code for Stages 1 to 9 exists, built under the `mvp` profile | `STAGE`, `stages.toml` comment | R-93, R-94 | Yes (`stages.toml`) |
| DEV-44 | Images pinned by digest (§4.5) | `grafana/otel-lgtm:latest` without a digest | `compose.yaml` | R-85 | Yes (`docs/production.md`) |
| DEV-45 | The authoritative design is v3.1 | `README.md` cites the design as v3.0 | `README.md` | R-88 | No |
| DEV-46 | Retrieval ledger written only by `retrieval` (insert-only), read by generation and validator (§9.4) | Ledger written by the Gateway's query-flow transaction as `lmqa_app`, which holds `select, insert` | `db/roles/grants.sql`, `services/gateway/src/gateway/query_flow.py` | R-31 | No |
| DEV-47 | Admin suspension cascades tenants to `suspended` with reason `workspace_frozen` (§7.7) | Workspace frozen; tenants keep status `active` and are denied only through rule 1; cascade functions unwired | `services/identity/src/identity/service.py` (`decide_admin`), `services/identity/src/identity/lifecycle.py` | R-17 | No |
| DEV-48 | Helper lookups owned by a non-login `policy_helper` role (§10.3) | Helpers are `SECURITY DEFINER` functions owned by `lmqa_owner` | `db/policies/10_helpers.sql`, `db/policies/11_access.sql`, `db/policies/15_force_rls.sql` | R-32 | No |
| DEV-49 | Migrations with Alembic and SQLAlchemy 2 async (§4.5, §18) | Plain SQL files applied by `libs/lmqa_db/src/lmqa_db/migrate.py`; synchronous `psycopg` pools | `db/migrations/`, `tools/db_migrate.py`, `libs/lmqa_db/src/lmqa_db/database.py` | R-78, R-85 | No |
| DEV-50 | Repository keeps design and spec under version control (§18 `docs/`) | `.gitignore` ignores `.kiro` and `project-blueprint`, so this spec and the design are not committed | `.gitignore` | R-88 | No |

## Open questions

| ID | Question | Why it matters | Affected |
| --- | --- | --- | --- |
| Q-01 | The split files differ from the master in two places: `8. Authentication with Auth0.md` has four numbered login-flow steps in §8.3 that the master omits (the master §8.3 has only the "No PHI" sentence), and `19. Quality system- real data, pytest, ruff and gates.md` has the R1 to R10 rules table in §19.1 that the master omits. All other sections match after normalizing table formatting. This document followed the master: §8.3 requirements come from the master's sentence plus §4.8, §17.3, D30, DEF-09 and DEF-58, and R-89 uses the master's references to R2, R4, R7 and R8. Should the split-file text be restored into the master? | Without the table, R1, R3, R5, R6, R9 and R10 are referenced by number but not defined in the authoritative file | R-20, R-89 |
| Q-02 | Kubernetes deferral scope: does it also defer production mTLS through cert-manager and SPIFFE-style identity (§9.2), Kubernetes network policies (§4.7) and Helm-deployed stores (§4.6), or only `infra/k8s/` overlays and Stage 11 cluster build-out? | Decides whether network isolation must be designed for Compose networks only in this spec | R-29, R-84, R-86, R-94 |
| Q-03 | `docs/production.md` says CI/CD workflows were skipped at the owner's request, while this request defers only Kubernetes. Are the CI workflows in scope now? | Gates cannot be signed or required without CI (§19.6) | R-19, R-90, R-93 |
| Q-04 | Keep, remove or add to the design the MVP features outside the design (chats with LLM query planning, profiles, named document shares, workspace visibility, usage counts, public website, LLM re-ranker, multi-key quota rotation)? | They change the access decision (DEV-14) and send question text to an LLM before retrieval (DEV-21) | R-4, R-44, R-80, R-81 |
| Q-05 | Migrate the MVP's `workspace` visibility and `document_shares` into matters, or keep rules 7a and 7b permanently? | The oracle, RLS and vector filter must agree on one rule set (G1.4) | R-4, R-35 |
| Q-06 | Embedding provider: the design defaults to self-hosted; the MVP sends document text to Gemini. Which is the target for the first real-data pilot? (D17 is "Confirm".) | Data boundary and BAA scope | R-50 |
| Q-07 | Vector store: cut over to Qdrant as designed, or adopt pgvector (the design's evaluated fallback, ADR 0004) as the default? | Changes R-35, R-36 and the Stage 5 gates | R-35, R-36 |
| Q-08 | Open "Confirm" decisions: D8 (Auth0 plan, region, BAA add-on), D10 (retention defaults per jurisdiction), D17 (self-hosting as default), D23 (reference cloud). Who confirms each, and by which stage? | Each blocks the stage that depends on it | R-19, R-50, R-61 |
| Q-09 | The request says to follow the design's architecture, not AWS-native by default. The design names AWS KMS, S3, CloudTrail and EventBridge as the reference adapters (A3, D23). Confirm AWS as the reference cloud for KMS and object storage, or name another cloud? | KeyGuard controls (§12.5) are written against AWS IAM and SCPs | R-51, R-54, R-57 |
| Q-10 | §8.3 role-claim behavior: the split file says the token role claim is a routing hint and a mismatch is denied and alerted. The master gives only DEF-09. Adopt the split-file wording? | R-20 criteria 6 and 7 depend on it | R-20 |
| Q-11 | The design says disclaimers and human-review workflows are product surface (§2.2) but does not define the human-review workflow. What is it? | R-100 criterion 4 cannot be made testable until defined | R-100 |
| Q-12 | Citation tag grammar: adopt the design's `[chunk_N]`, or amend the design to the MVP's `[S_N]`? | V1 and the prompt protocol must match | R-46, R-47 |
| Q-13 | Is the MVP's LLM entailment pass for V6 acceptable as an interim step, given that it breaks the "no generative LLM" and determinism rules? | Affects whether Stage 7 can start before the NLI model is calibrated | R-47 |
| Q-14 | §19.6 refers to a companion document, "MVP Prototype Report and Process", that defines the `mvp` profile (release M1). It was not provided. Should this spec target the `full` profile only? | Decides which gate sizes apply | R-93, R-94 |
| Q-15 | Should `.kiro/` and `project-blueprint/` stop being git-ignored so the spec and design are versioned with the code? | Traceability of requirements to commits | R-88 |
| Q-16 | `STAGE = 0` while Stages 1 to 9 code exists. Re-run the gates from Stage 0 under the `full` profile and advance stage by stage, or rebaseline? | Gatekeeper rule 1 rejects the current tree (DEV-43) | R-93, R-94 |
| Q-17 | Accept the custom SSE parser in `frontend/src/lib/sse.ts` if it passes G8.4, or require `eventsource-parser` as §17.3 states? | §17.3 names the library as mandatory | R-82 |
| Q-18 | The PRD guide asks for a dual output: an HTML PRD in `documents/` with an SVG architecture diagram, and a current-year web check of every technology with source links. Neither was produced in this pass. Should they be? | PRD guide quality checklist | Technology landscape |
| Q-19 | Appendix A lists 64 defects with resolutions. This document covers each resolution through the section it names. Should each DEF also get its own regression test requirement? | Traceability | All |
| Q-20 | `IPC.pdf` (not in the manifest) sits in the repository root. Remove it, or add it to the manifest with its licence? | Real-data rule: manifest is the only fixture source | R-89, R-98 |
| Q-21 | §5.7 reason codes for emergency access are "from a fixed list" but the list is not given. What is the list? | R-7 criterion 2 needs it | R-7 |
| Q-22 | §13.6 says "Admin pending approval beyond N days" without a value for N. What is N? | R-63 criterion 1 needs it | R-63 |
| Q-23 | The design never defines a "live" membership; R-1 criterion 7 assumes `pending_approval`, `active` and `suspended`. Is that the intended set? | Decides the one-live-membership index predicate | R-1 |
| Q-24 | Does a pending or suspended caller on a listed route get 403 or 404 (§15.1 vs §17.1)? | R-2 criteria 2, 8 and 9 must agree | R-2 |
| Q-25 | §15.1 gives one example of a "system-level refusal" 403. What is the full list? | R-2 criterion 8 cannot be tested in full without it | R-2 |
| Q-26 | Successor transfer timing (§5.3, §7.8): when does the 72-hour cooling-off start, when are notices sent, and whose passkey step-up is required? | R-3 criteria 5 and 6 depend on it | R-3 |
| Q-27 | Does the RLS-vs-oracle comparison cover every role, table and operation, or only SELECT (§10.3 vs gate G1.4)? | Sets the scope of R-4 criterion 5 | R-4 |
| Q-28 | What is the uploader's tier ceiling for an admin, and for a private document with no matter (§5.5)? **Resolved:** admin ceiling is tier 4 (source: §5.4 rule 4, admin reads all tiers on matter documents). **Resolved by assumption:** a private document with no matter has ceiling tier 4 (only the owner reads it, and §5.4 rule 3 lets the owner read all tiers). | R-5 criterion 3 cannot be tested for those cases | R-5 |
| Q-29 | Is the limit of 5 emergency exceptions "per day" a calendar day (in which time zone) or a rolling 24 hours (§5.7)? **Resolved by assumption:** rolling 24 hours, no time zone; limit configurable, at most 5 in production (Appendix C); matches `scope_admin.request_emergency`. | Sets the boundary test of R-7 criterion 3 | R-7 |
| Q-30 | Who is the "affected tenant" of a break-glass session: owners of documents read in it, or every tenant of the workspace (§5.8)? **Resolved by assumption:** each tenant who owns a private document read or returned in a query during the session (least disclosure; §5.8 is about a tenant's private documents, and all tenants are already notified when the flag is enabled). | Sets the audience of R-8 criterion 6 | R-8 |
| Q-31 | When does a saga step count as permanently failed (retry count, error class) and trigger compensation instead of retry (§7.2, §6.3)? **Resolved by assumption:** permanent on a non-retryable error, or on the 5th failed attempt with exponential backoff, configurable (§6.3 and G2.2 require retry then compensation but give no count). | R-12 criterion 4 has no testable trigger | R-12 |
| Q-32 | What is the per-IP organization creation limit and its window (§7.2)? **Resolved by assumption:** 3 organizations per IP per rolling 24 hours, configurable (creation is rare and each one creates KMS keys and an Auth0 Organization). | R-12 criterion 7 has no number | R-12 |
| Q-33 | What are the threshold, window and reset period of the per-lookup-ID circuit breaker (§7.6)? **Resolved by assumption:** opens after 10 failed attempts on one lookup ID within 15 minutes, closes 15 minutes later, configurable (mirrors the 15-minute window of the per-user limit in §7.6). | R-16 criterion 7 cannot be tested for lookup IDs | R-16 |
| Q-34 | Does the `co_owner_set` 72-hour cooling-off start at invite or at acceptance, and when are admins notified (§7.5, §6.7)? **Resolved:** the cooling-off starts at acceptance (source: §6.7, the invitee's acceptance is the approval and the wait follows approval). **Resolved by assumption:** admins are notified at acceptance, so the notice covers the whole wait. | Sets timing in R-15 criterion 3 | R-15 |
| Q-35 | What does "re-validate walls and break-glass sessions" do on a successor transfer: end active break-glass sessions, re-check walls on the new admin, or both (§7.8)? **Resolved by assumption:** revoke every active break-glass session, keep every wall in force and bump the scope version (sessions belonged to the outgoing admin and `admin_can_read_private` is reset to off; walls must survive the transfer). | R-18 criterion 4 has no testable outcome for that step | R-18 |

## Out of scope

- Kubernetes: `infra/k8s/` base and overlays, Kubernetes network policies, Helm-deployed stores and EKS (user deferral; see Q-02).
- Legal or medical advice (§2.2 non-goal).
- Making a wrong source document right (§2.2 non-goal).
- Languages other than English in v1 (§2.4 A6).
- Multiple memberships per user and role changes in v1 (§5.1, D7).
- Application source code, production credentials, vendor contracts and legal advice inside the design itself (§0).

## Success metrics

All targets come from the design's gates and budgets.

| Metric | Target | Measurement |
| --- | --- | --- |
| Unverified sentences released | 0 across at least 1,000 live queries | G7.7 |
| Precision of "supported" verdicts | ≥ 0.99 on at least 300 human-labeled pairs per domain | G7.3 |
| Cross-scope leaks | 0 in every output channel | G5.4, G10.2 |
| RLS versus oracle disagreement | 0 over at least 20,000 generated scenarios | G1.4 |
| Revocation of new requests | p99 ≤ 2 s (≤ 5 s with pub/sub down) | G3.4 |
| Open stream cut after revocation | ≤ 2 s (≤ 15 s fallback) | G3.4 |
| Time to first verified sentence | p95 ≤ 6 s | G7.12 |
| Validator time per sentence | p95 ≤ 150 ms on CPU | G7.12 |
| Retrieval latency with 5,000 grants | p95 ≤ 800 ms at 1,000,000 chunks | G5.9 |
| Ingestion of a 200-page scanned PDF | p95 ≤ 10 minutes | G4.12 |
| Page-range accuracy | ≥ 98 percent exact on at least 200 human-verified chunks | G4.3 |
| Disaster recovery | RPO ≤ 5 minutes, RTO ≤ 4 hours | G9.10 |
| Retrieval quality | Recall@k, MRR, nDCG at or above `eval/floors.toml` | G5.3, G10.6 |

## Design heading coverage

This table lists every `##` and `###` heading of the master design (168 headings, extracted with `grep -n "^##"` from `Legal-Medical-QA-Master-System-Design-v3.1.md`; "Line" is the line number in that file). Coverage values:

- **Covered**: at least one requirement states the section's behavior.
- **Covered (indirect)**: the section summarizes or cross-references content that other requirements state.
- **Covered; part deferred by user (Kubernetes)**: the section is covered except for Kubernetes content, which the user deferred.
- **None (flagged)**: no requirement covers the section. The note says why.

Flagged sections: §0 Document control, §3.2 Terminology and Appendix A Defect register.

| Line | Heading | Requirement IDs | Coverage | Note |
| --- | --- | --- | --- | --- |
| 7 | `##` 0. Document control | — | **None (flagged)** | Document metadata only; no system behavior to require |
| 18 | `##` 1. Executive summary | R-1, R-83, R-100 | Covered | Parent section |
| 20 | `###` 1.1 What the system is | R-1, R-47, R-48, R-100 | Covered | |
| 26 | `###` 1.2 The model in one picture | R-1, R-3, R-4, R-19, R-32, R-48 | Covered | |
| 65 | `###` 1.3 What changed in v3.0 | R-6, R-7, R-10, R-15, R-21, R-36, R-54 to R-56, R-66 to R-77, R-93 | Covered (indirect) | Change summary; each row points to a section covered elsewhere |
| 80 | `###` 1.4 Delivery in twelve gated stages | R-93, R-94 | Covered | |
| 99 | `###` 1.5 What this document proves and what it does not | R-96, R-97 | Covered | |
| 103 | `##` 2. Scope, goals, non-goals and constraints | R-100, R-89 | Covered | Parent section; see also Constraints C1 to C9 |
| 105 | `###` 2.1 Goals | R-4, R-45, R-47, R-65, R-83, R-100 | Covered | |
| 115 | `###` 2.2 Non-goals | R-100 | Covered | Also listed under Out of scope |
| 120 | `###` 2.3 Constraints that shape the plan | R-86, R-89 | Covered | Also Constraints C1 to C4 |
| 131 | `###` 2.4 Assumptions | R-1, R-89 | Covered | Also Constraints C5 to C9; EKS in A3 deferred by user |
| 140 | `##` 3. Design principles and terminology | R-1, R-32 | Covered | Parent section |
| 142 | `###` 3.1 Principles | R-1, R-4, R-10, R-16, R-32, R-34, R-48, R-51, R-54, R-60, R-66, R-83 | Covered | |
| 158 | `###` 3.2 Terminology | — | **None (flagged)** | Terminology only; terms are defined in the Glossary |
| 179 | `###` 3.3 Rename map for the earlier documents | R-88 | Covered | |
| 190 | `##` 4. System architecture | R-83 | Covered | Parent section |
| 192 | `###` 4.1 Three planes | R-83 | Covered | |
| 200 | `###` 4.2 Service catalog | R-29, R-83 | Covered | |
| 220 | `###` 4.3 Master system design | R-83 | Covered | |
| 342 | `###` 4.4 Query flow with gated release | R-31, R-48 | Covered | |
| 383 | `###` 4.5 Technology stack and version ledger | R-85 | Covered | EKS deferred by user |
| 424 | `###` 4.6 Environments and what is real in each | R-86 | Covered; part deferred by user (Kubernetes) | Managed or Helm-deployed stores for staging and production deferred |
| 440 | `###` 4.7 Allowed calls and import boundaries | R-84 | Covered; part deferred by user (Kubernetes) | Network policies in Kubernetes deferred; Compose network rules stay in scope |
| 457 | `###` 4.8 Compatibility constraints and how the design handles them | R-87 | Covered | |
| 485 | `##` 5. Roles, containment and access rules | R-1 to R-9 | Covered | Parent section |
| 487 | `###` 5.1 Containment rules | R-1 | Covered | |
| 506 | `###` 5.2 Permission matrix | R-2 | Covered | |
| 529 | `###` 5.3 The Super Admin boundary | R-3 | Covered | |
| 539 | `###` 5.4 Document visibility and the access decision | R-4 | Covered | |
| 560 | `###` 5.5 Confidentiality tiers | R-5 | Covered | |
| 564 | `###` 5.6 Ethical walls (legal workspaces) | R-6 | Covered | |
| 575 | `###` 5.7 Clinical emergency access (medical workspaces) | R-7 | Covered | |
| 589 | `###` 5.8 Break-glass reading of a tenant's private documents | R-8 | Covered | |
| 593 | `###` 5.9 Owner-linked admin identities | R-9 | Covered | |
| 603 | `##` 6. Lifecycle state machines | R-10 | Covered | Parent section |
| 605 | `###` 6.1 Principles | R-10 | Covered | |
| 613 | `###` 6.2 Membership | R-10, R-23 | Covered | |
| 639 | `###` 6.3 Workspace | R-10, R-13, R-17 | Covered | |
| 665 | `###` 6.4 Organization | R-10, R-12, R-56 | Covered | |
| 693 | `###` 6.5 Documents and index state | R-10, R-36, R-41, R-42 | Covered | |
| 697 | `###` 6.6 Join codes | R-10, R-16 | Covered | |
| 701 | `###` 6.7 Governance requests | R-10, R-15, R-18, R-55, R-69, R-73 | Covered | |
| 718 | `###` 6.8 Access sessions | R-7, R-8, R-10, R-67 | Covered | |
| 722 | `##` 7. Onboarding, codes and lifecycle events | R-11 to R-18 | Covered | Parent section |
| 724 | `###` 7.1 Common entry | R-11 | Covered | |
| 731 | `###` 7.2 Path A: Super Admin creates an organization | R-12 | Covered | |
| 762 | `###` 7.3 Path B: Admin joins an organization | R-13 | Covered | |
| 788 | `###` 7.4 Path C: Tenant joins a workspace | R-14 | Covered | |
| 792 | `###` 7.5 Co-owner | R-15 | Covered | |
| 796 | `###` 7.6 Code specification | R-16 | Covered | |
| 821 | `###` 7.7 Lifecycle events and effects | R-17 | Covered | |
| 843 | `###` 7.8 Successor transfer | R-18 | Covered | |
| 847 | `##` 8. Authentication with Auth0 | R-19 to R-27 | Covered | Parent section |
| 849 | `###` 8.1 Responsibility split and plan check | R-19 | Covered | |
| 869 | `###` 8.2 Tenants and configuration as code | R-19 | Covered | |
| 883 | `###` 8.3 Login flow | R-20 | Covered | Master text is one sentence; see Q-01 and Q-10 |
| 887 | `###` 8.4 Authentication strength: passkeys for the highest-power roles | R-21 | Covered | |
| 904 | `###` 8.5 Token verification at the Gateway | R-22 | Covered | |
| 912 | `###` 8.6 Suspension and revocation in seconds | R-23 | Covered | |
| 928 | `###` 8.7 Step-up authentication | R-24 | Covered | |
| 932 | `###` 8.8 Isolating the Auth0 Management API | R-25 | Covered | |
| 936 | `###` 8.9 SSO and automatic membership | R-26 | Covered | |
| 940 | `###` 8.10 Testing identity for real | R-27 | Covered | |
| 949 | `##` 9. Internal trust: service identity and context tokens | R-28 to R-31 | Covered | Parent section |
| 951 | `###` 9.1 The context token | R-28 | Covered | |
| 962 | `###` 9.2 Service credentials | R-29 | Covered | Production mTLS via cert-manager may fall under the Kubernetes deferral (Q-02) |
| 975 | `###` 9.3 Signed job envelope | R-30 | Covered | |
| 979 | `###` 9.4 The retrieval ledger | R-31 | Covered | |
| 983 | `##` 10. Layered isolation enforcement | R-32 to R-40 | Covered | Parent section |
| 985 | `###` 10.1 The five layers | R-32, R-63 | Covered | |
| 998 | `###` 10.2 Partition key per store | R-33 | Covered | |
| 1009 | `###` 10.3 PostgreSQL specifics | R-4, R-32, R-78 | Covered | |
| 1024 | `###` 10.4 Behavior when a dependency fails | R-34 | Covered | |
| 1037 | `###` 10.5 Vector search isolation | R-35 | Covered | |
| 1051 | `###` 10.6 Index consistency: PostgreSQL is the authority | R-36 | Covered | |
| 1072 | `###` 10.7 Semantic cache | R-37 | Covered | |
| 1081 | `###` 10.8 Async ingestion and fairness | R-38 | Covered | |
| 1085 | `###` 10.9 LLM and prompt layer | R-39 | Covered | |
| 1089 | `###` 10.10 Pooled by default, siloed when required | R-40 | Covered | |
| 1093 | `##` 11. The RAG pipeline | R-41 to R-50 | Covered | Parent section |
| 1095 | `###` 11.1 Ingestion | R-41, R-42 | Covered | |
| 1116 | `###` 11.2 Chunk model and citations | R-43 | Covered | |
| 1131 | `###` 11.3 Retrieval | R-44 | Covered | |
| 1141 | `###` 11.4 Token optimization | R-45 | Covered | |
| 1153 | `###` 11.5 Prompt and citation protocol | R-46 | Covered | |
| 1161 | `###` 11.6 Citation validation and gated delivery | R-47, R-48 | Covered | |
| 1195 | `###` 11.7 Prompt and model lifecycle | R-49 | Covered | |
| 1199 | `###` 11.8 LLM and embedding provider boundary | R-50 | Covered | |
| 1203 | `##` 12. Encryption and key management | R-51 to R-59 | Covered | Parent section |
| 1205 | `###` 12.1 Key hierarchy | R-51 | Covered | |
| 1242 | `###` 12.2 What is encrypted | R-51 | Covered | |
| 1252 | `###` 12.3 Object encryption | R-52 | Covered | |
| 1260 | `###` 12.4 Rotation | R-53 | Covered | |
| 1267 | `###` 12.5 Deletion guardrails | R-54 | Covered | |
| 1279 | `###` 12.6 Two-person approval, windows and sealing | R-55 | Covered | |
| 1292 | `###` 12.7 The organization destruction ritual | R-56 | Covered | |
| 1308 | `###` 12.8 Backup, disaster recovery and escrow | R-57 | Covered | |
| 1316 | `###` 12.9 Shredding semantics and backups | R-58 | Covered | |
| 1326 | `###` 12.10 Local mode and repository hygiene | R-59 | Covered | |
| 1331 | `##` 13. Audit, alerting, quotas and compliance mapping | R-60 to R-65 | Covered | Parent section |
| 1333 | `###` 13.1 Event model | R-60 | Covered | |
| 1342 | `###` 13.2 Sealed payloads | R-60 | Covered | |
| 1346 | `###` 13.3 Chains, anchoring and retention | R-61 | Covered | |
| 1354 | `###` 13.4 What is recorded | R-62 | Covered | |
| 1365 | `###` 13.5 Who can read what | R-62 | Covered | |
| 1374 | `###` 13.6 Detection signals and alerts | R-63 | Covered | |
| 1396 | `###` 13.7 Quotas and noisy-neighbor control | R-64 | Covered | |
| 1400 | `###` 13.8 Retention versus immutability | R-61 | Covered | |
| 1404 | `###` 13.9 Compliance mapping (for counsel review) | R-65 | Covered | |
| 1422 | `##` 14. Platform operator access | R-66 to R-69 | Covered | Parent section |
| 1424 | `###` 14.1 Principles | R-66 | Covered | |
| 1428 | `###` 14.2 Identities and roles | R-66 | Covered | |
| 1442 | `###` 14.3 Access types and approvals | R-67 | Covered | |
| 1452 | `###` 14.4 Limits and lifecycle | R-67 | Covered | |
| 1465 | `###` 14.5 What operators can never do | R-68 | Covered | |
| 1469 | `###` 14.6 Lost Super Admin (owner recovery) | R-69 | Covered | |
| 1473 | `##` 15. API surface | R-70 to R-77 | Covered | Parent section |
| 1475 | `###` 15.1 Rules for every endpoint | R-70 | Covered | |
| 1485 | `###` 15.2 Onboarding (audience `onboarding`) | R-71 | Covered | |
| 1495 | `###` 15.3 Session | R-71 | Covered | |
| 1502 | `###` 15.4 Organization (Super Admin and co-owner) | R-72 | Covered | |
| 1519 | `###` 15.5 Governance requests | R-73 | Covered | |
| 1528 | `###` 15.6 Workspace (Admin) | R-74 | Covered | |
| 1550 | `###` 15.7 Data plane (Admin and Tenant) | R-75 | Covered | |
| 1567 | `###` 15.8 Operator plane (`ops.<product-domain>`, separate ingress and identity provider) | R-76 | Covered | |
| 1580 | `###` 15.9 Internal endpoints (not routable from outside) | R-77 | Covered | |
| 1591 | `##` 16. Data model | R-78, R-79 | Covered | Parent section |
| 1593 | `###` 16.1 Conventions | R-78 | Covered | |
| 1597 | `###` 16.2 Core tables | R-78 | Covered | |
| 1627 | `###` 16.3 Policy summary by role | R-79 | Covered | |
| 1638 | `##` 17. Frontend design (Next.js 16) | R-80 to R-82 | Covered | Parent section |
| 1640 | `###` 17.1 Structure and routing | R-80 | Covered | |
| 1673 | `###` 17.2 Key surfaces | R-81 | Covered | |
| 1681 | `###` 17.3 Security and streaming rules | R-82 | Covered | |
| 1693 | `##` 18. Repository structure and tooling | R-88 | Covered; part deferred by user (Kubernetes) | `infra/k8s/` (base and overlays) deferred |
| 1772 | `##` 19. Quality system: real data, `pytest`, `ruff` and gates | R-89 to R-93 | Covered | Parent section |
| 1774 | `###` 19.1 Real-data rules | R-89 | Covered | R1 to R10 table only in the split file (Q-01) |
| 1781 | `###` 19.2 Test taxonomy | R-90 | Covered | |
| 1799 | `###` 19.3 `ruff` configuration | R-91 | Covered | |
| 1841 | `###` 19.4 `pytest` configuration | R-90 | Covered | |
| 1861 | `###` 19.5 Coverage and mutation thresholds | R-92 | Covered | |
| 1872 | `###` 19.6 Gate mechanics | R-93 | Covered | |
| 1896 | `###` 19.7 Definition of done and failure protocol | R-93 | Covered | |
| 1902 | `##` 20. Staged delivery plan | R-94 | Covered | Parent section |
| 1921 | `###` Stage 0 — Foundation and real dependencies | R-94, R-27, R-30, R-59, R-84, R-85, R-86, R-88, R-89, R-98 | Covered | |
| 1942 | `###` Stage 1 — Data layer and key management | R-94, R-4, R-10, R-32, R-40, R-51, R-54, R-58, R-61, R-78 | Covered | |
| 1962 | `###` Stage 2 — Identity and onboarding on Auth0 | R-94, R-11 to R-19, R-21, R-24, R-25 | Covered | |
| 1982 | `###` Stage 3 — Gateway and internal trust | R-94, R-2, R-22, R-23, R-24, R-28, R-34, R-64, R-70 | Covered | |
| 2000 | `###` Stage 4 — Ingestion | R-94, R-30, R-36, R-38, R-41, R-42, R-43, R-52, R-58 | Covered | |
| 2020 | `###` Stage 5 — Retrieval | R-94, R-4 to R-8, R-31, R-35, R-44 | Covered | |
| 2040 | `###` Stage 6 — Generation | R-94, R-37, R-39, R-45, R-46, R-49, R-50 | Covered | |
| 2058 | `###` Stage 7 — Citation validation and gated delivery | R-94, R-47, R-48 | Covered | |
| 2078 | `###` Stage 8 — Frontend | R-94, R-20, R-80, R-81, R-82 | Covered | |
| 2096 | `###` Stage 9 — Governance, audit, operators and lifecycle | R-94, R-18, R-55, R-56, R-57, R-60 to R-64, R-66 to R-69 | Covered | |
| 2116 | `###` Stage 10 — System verification | R-94, R-85, R-95, R-96 | Covered | |
| 2134 | `###` Stage 11 — Production readiness | R-94, R-97 | Covered; part deferred by user (Kubernetes) | Production infrastructure on Kubernetes and the staging and production overlays deferred; G11.2 to G11.10 in scope |
| 2152 | `##` 21. Isolation and verification suite | R-95 | Covered | |
| 2186 | `##` 22. Performance and capacity plan | R-96 | Covered | |
| 2204 | `##` 23. Threat model | R-3, R-6, R-7, R-10, R-11, R-16, R-17, R-18, R-20, R-21, R-25, R-28, R-35, R-36, R-37, R-38, R-39, R-48, R-54, R-58, R-61, R-64, R-67, R-85, R-89 | Covered (indirect) | No requirement of its own; each threat's controls are required in the listed requirements |
| 2241 | `##` 24. Decisions and open items | R-1, R-6 to R-9, R-12, R-14 to R-16, R-18, R-20, R-21, R-28, R-30, R-35, R-37, R-40, R-41, R-48, R-50, R-60, R-61, R-66, R-82, R-85, R-88 to R-91, R-98 | Covered | D8, D10, D17 and D23 are open (Q-08, Q-09) |
| 2280 | `##` 25. Residual risks, assumptions and external validation | R-97 | Covered | Parent section |
| 2282 | `###` 25.1 Residual risks | R-9, R-97, R-100 | Covered | Residual risks; bounding controls are in the listed requirements |
| 2300 | `###` 25.2 Trust assumptions | R-97 | Covered | Trust assumptions also listed as Constraint C10 |
| 2310 | `###` 25.3 What editing cannot close | R-96, R-97 | Covered | |
| 2325 | `##` Appendix A — Defect register | — | **None (flagged)** | Defect register; each resolution is required through the section it names (Q-19) |
| 2397 | `##` Appendix B — Real-data corpus and evaluation sources | R-98 | Covered | |
| 2415 | `##` Appendix C — Configuration catalog (names only) and policy minimums | R-99 | Covered | |
