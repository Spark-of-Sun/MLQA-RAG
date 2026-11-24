# Implementation Plan: legal-medical-qa (MVP to v3.1)

## Overview

The plan takes the existing MVP code in this repository to the v3.1 architecture in `design.md`, stage by stage,
following the design's "Migration path from MVP to v3.1" table. Each top-level task is one stage. Its sub-tasks
close the deviations (DEV-xx) the stage owns, and the last sub-task of each stage enables the stage's flags in
`contracts/features.toml`, deletes the MVP path the flag replaces (design Approach 3) and advances `STAGE` once the
gatekeeper attests twice (R-93, R-94). Kubernetes is deferred: Compose networks stand in for network policies
(Q-02, Q-40), and no task targets Kubernetes.

Languages: Python for services, libraries, tools and tests (pytest, Hypothesis); TypeScript for `frontend/`.
Property tests run against the real Compose stores (C1, R-89), use at least 100 examples (Property 1: at least
20,000 scenarios) and carry the tag `# Feature: legal-medical-qa, Property {n}: {title}`.

Tasks marked "pending Q-xx" implement the v3.1 default that the design states; confirm the open question before
starting that task.

## Tasks

- [ ] 1. Stage 0: Toolchain, CI and repository baseline
  - [x] 1.1 Tighten ruff and fix findings
    - Set `select = ["ALL"]` and line length 100 in `pyproject.toml`; fix findings across `libs/`, `services/`, `tools/`, tests
    - _Requirements: 91.1, 85; closes DEV-33 (ruff part)_
  - [x] 1.2 Make pyright blocking and add coverage and test-taxonomy settings
    - `pyright` blocking under the `full` profile; `fail_under` coverage and mutation thresholds; stage and kind markers; add `pytest-asyncio`, Schemathesis and Playwright dev dependencies
    - _Requirements: 90, 92, 93; closes DEV-33_
  - [x] 1.3 Move migrations to Alembic
    - Add an Alembic environment in `libs/lmqa_db`; existing SQL files 0001 to 0005 become revisions executed with `op.execute`; replace `migrate.py` entry point (KD-12)
    - _Requirements: 78, 85; closes DEV-49_
  - [x] 1.4 Add CI workflows `ci`, `gates`, `isolation`, `nightly-live`, `security`, `release` under `.github/workflows` (pending Q-03)
    - _Requirements: 85, 93; closes DEV-36_
  - [x] 1.5 Pin every image in `compose.yaml` by digest, including `grafana/otel-lgtm`, and add a static check that fails on an unpinned image
    - _Requirements: 85; closes DEV-44_
  - [x] 1.6 Bring the corpus to Appendix B minimums
    - Extend `corpus/manifest.toml` to 150 legal and 150 medical documents with format quotas; delete fixtures not in the manifest (Q-20); `tools/load_corpus` loads through the real onboarding and upload APIs
    - _Requirements: 89, 98; closes DEV-37, DEV-42_
  - [x] 1.7 Remove the demo token signer from `make demo` and `make demo-web` and any local path that signs identity tokens
    - _Requirements: 27, 89; closes DEV-35_
  - [x] 1.8 Extend `tools/gatekeeper.py` and `make doctor`
    - Gatekeeper: twice-in-a-row rule, CI-signed attestations, profiles, flag-to-gate binding; doctor: dependency and cross-component compatibility checks
    - _Requirements: 86, 87, 93_
  - [x] 1.9 Repository hygiene
    - Un-ignore `.kiro` and `project-blueprint` in `.gitignore` (Q-15); README cites v3.1; rebaseline `STAGE` under the `full` profile (Q-16)
    - _Requirements: 88, 94; closes DEV-43, DEV-45, DEV-50_
  - [ ]* 1.10 Write unit tests for the gatekeeper twice-in-a-row rule, the unpinned-image check and doctor
    - _Requirements: 85, 86, 93_
  - [ ] 1.11 Close Stage 0: run the Stage 0 gate under `full`, record the attestation, keep `STAGE = 0` as the attested baseline
    - _Requirements: 93, 94_

- [ ] 2. Checkpoint - Stage 0
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Stage 1: Schema, RLS, access decision, field encryption and audit chains
  - [x] 3.1 Apply migrations 0006 to 0008 as Alembic revisions and create the role model
    - One `NOBYPASSRLS` non-owner role per service (design "Database roles"); non-login `policy_helper` owns `SECURITY DEFINER` helpers; `super_admin` policy set limited to the §5.3 tables; remove the `lmqa_system` pool; `lmqa_db.connect(service)` and `scoped(pool, claims)` with `SET LOCAL app.*`
    - _Requirements: 3.1, 3.3, 29, 32, 79; closes DEV-13, DEV-38, DEV-48_
  - [x] 3.2 Tenancy and membership schema
    - Membership states `pending_approval`, `active`, `rejected`, `suspended`, `removed`; unique live index over `pending_approval`, `active`, `suspended` (Q-23); CHECK `approver_id <> user_id`; no role-update path; workspace `pending → provisioning → active`
    - _Requirements: 1.3, 1.4, 1.7, 78; closes DEV-17 (schema part)_
  - [x] 3.3 Lifecycle machines as data
    - Transition tables and triggers generated from `contracts/state-machines.yaml`; `lmqa_models.Machine.load` and `Machine.check` raising `IllegalTransition`; reject membership changes made by the member
    - _Requirements: 10.2, 10.4, 10.5, 10.6_
  - [x] 3.4 Access decision rules 1 to 8 (pending Q-05, Q-37)
    - `app_can_read` implements §5.4 rules 1 to 8 only; migrate out rules 7a and 7b, `workspace` visibility and `document_shares`; enable matters, grants (`max_tier`, `expires_at`), walls, emergency access and break-glass from behind `matters_walls_tiers`; upload tier ceiling; walls bump `scope_hash` and `scope_version` in `principal_v`
    - _Requirements: 4.1, 4.5, 4.6, 5.3, 5.4, 6.2, 6.4, 6.9, 6.10, 7, 8; closes DEV-14, DEV-15_
  - [x] 3.5 Align `lmqa_testing.oracle.can_read` to rules 1 to 8 and add `lmqa_testing.strategies` (worlds, principals, codes, sentences with numbers and tags, audit event sequences, timed attempt sequences)
    - _Requirements: 4.1, 95_
  - [x] 3.6 Freeze MVP-only features (chats with LLM query planning, profiles, named shares, workspace visibility, usage counts, public site, LLM re-ranker, quota rotation) behind flags that stay off and outside the access decision (pending Q-04, Q-39)
    - _Requirements: 4.1, 39; DEV-21 stays open until Q-04 is answered_
  - [x] 3.7 Field encryption through `lmqa_keys` (pending Q-36)
    - Workspace content keys, document keys, workspace-month audit keys, cache keys; AES-256-GCM with scope AAD on titles, chunk text, questions, answers and contact fields; key rotation keeps old ciphertext readable; OpenBao in local key mode; one-time re-encryption job, then drop plaintext columns
    - _Requirements: 51, 53, 59; closes DEV-09 (columns)_
  - [x] 3.8 Audit chains
    - One chain per workspace plus an organization control chain; monthly partitions; checkpoints on partition detach; HPKE sealing to the workspace-month key in `lmqa_audit.append`; UPDATE and DELETE rejected by trigger
    - _Requirements: 60.2, 60.4, 61.1, 61.5; closes DEV-18_
  - [x] 3.9 Redaction: `lmqa_security.redact` covers code, token and content fields; audit metadata builders accept no free text
    - _Requirements: 16.10, 60.5_
  - [ ]* 3.10 Write property test for RLS against the oracle
    - **Property 1: RLS equals the access oracle** (at least 20,000 scenarios)
    - **Validates: Requirements 3.1, 3.4, 4.1, 4.5, 4.6, 5.4, 6.2, 6.9, 7, 8**
  - [ ]* 3.11 Write property test for cross-scope foreign keys
    - **Property 4: Cross-scope references are rejected**
    - **Validates: Requirements 1.3, 1.4**
  - [ ]* 3.12 Write property test for the upload tier ceiling
    - **Property 9: Upload tier ceiling**
    - **Validates: Requirements 5.3**
  - [ ]* 3.13 Write property test for live memberships
    - **Property 16: One live membership per user**
    - **Validates: Requirements 1.7**
  - [ ]* 3.14 Write property test for lifecycle transitions
    - **Property 17: Lifecycle transitions match the declaration**
    - **Validates: Requirements 10.2, 10.4, 10.5, 10.6, 41, 66**
  - [ ]* 3.15 Write property test for field encryption
    - **Property 31: Encryption round trip and scope binding** (fields and rotation; objects added in 9.2)
    - **Validates: Requirements 51, 53**
  - [ ]* 3.16 Write property test for sealed audit payloads
    - **Property 32: Sealed audit payloads**
    - **Validates: Requirements 60.2, 60.4**
  - [ ]* 3.17 Write property test for audit chain integrity
    - **Property 33: Audit chain integrity**
    - **Validates: Requirements 58, 61.1, 61.5**
  - [ ]* 3.18 Write property test for sensitive text in metadata and logs
    - **Property 35: No sensitive text in metadata or logs**
    - **Validates: Requirements 16.10, 60.5**
  - [ ]* 3.19 Write unit tests for policy catalog and defaults
    - No document or chunk policy for `super_admin` or operator roles; every runtime role `NOBYPASSRLS`; CHECK constraints; `admin_can_read_private = false`; emergency daily limit; break-glass session expiry
    - _Requirements: 3.3, 7, 8, 32, 79_
  - [ ] 3.20 Close Stage 1: enable Stage 1 flags, delete the replaced MVP access paths, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 4. Checkpoint - Stage 1
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Stage 2: Identity, onboarding, join codes, step-up and sessions
  - [x] 5.1 Auth0 configuration as code in `infra/auth0`
    - Organizations; `main` audience requires an organization and `onboarding` denies one; auth-strength names `passkey`, `webauthn_mfa`, `otp_mfa`, `password` in `lmqa_auth`; Management API credentials held only by identity-worker
    - _Requirements: 19, 21, 25; closes DEV-10, DEV-41_
  - [ ] 5.2 Organization creation and provisioning saga
    - `create_organization` creates the organization `pending` and starts the saga; required `deployment_type` and `data_region`; retry with backoff and compensation on permanent failure (pending Q-31)
    - _Requirements: 12; closes DEV-16, DEV-40_
  - [ ] 5.3 Join code generation, storage and verification
    - Crockford Base32, 8-character lookup ID, Luhn mod 32 check; HMAC under a versioned pepper; lookup by ID and constant-time compare; rotation; uniform failure message with the true reason in audit; uses counted once per created membership
    - _Requirements: 16.1, 16.2, 16.5, 16.6, 16.8, 16.12_
  - [ ]* 5.4 Write property test for join code format
    - **Property 11: Join code format**
    - **Validates: Requirements 16.1**
  - [ ]* 5.5 Write property test for code verification and rotation
    - **Property 12: Join code verification round trip and rotation**
    - **Validates: Requirements 16.2, 16.5, 16.6**
  - [ ] 5.6 Move code-attempt limits and the per-lookup-ID breaker to Valkey (Q-33 defaults: 5 per user per 15 min, 20 per IP per hour, breaker 10 in 15 min)
    - _Requirements: 16.7; closes DEV-27 (identity part)_
  - [ ]* 5.7 Write property test for code-attempt limits
    - **Property 13: Code-attempt limits**
    - **Validates: Requirements 16.7**
  - [ ]* 5.8 Write property test for the uniform failure message
    - **Property 14: Uniform failure message**
    - **Validates: Requirements 16.8**
  - [ ]* 5.9 Write property test for code use counting
    - **Property 15: Code use counting**
    - **Validates: Requirements 16.12**
  - [ ] 5.10 Onboarding flows
    - Common onboarding entry; admin joins an organization; tenant joins a workspace; owner-linked admin identities; co-owner; SSO automatic membership; membership machines use §6.2 states and `remove`
    - _Requirements: 9, 11, 13, 14, 15, 26; closes DEV-17, DEV-19 (co-owner part)_
  - [ ] 5.11 Lifecycle events and cascades: admin suspension moves active tenants to `suspended` with `workspace_frozen`
    - _Requirements: 17; closes DEV-47_
  - [ ]* 5.12 Write property test for the suspension cascade
    - **Property 19: Suspension cascade**
    - **Validates: Requirements 17**
  - [ ] 5.13 Per-role step-up in `contracts/authz-matrix.yaml` and a Gateway step-up decision (300 s, required strength) for code generation and rotation, approvals, removals, policy changes and governance approvals
    - _Requirements: 2.5, 24; closes DEV-29_
  - [ ]* 5.14 Write property test for the step-up decision
    - **Property 7: Step-up decision**
    - **Validates: Requirements 2.5, 24**
  - [ ] 5.15 Frontend BFF sessions in Valkey by default with an opaque session ID; privileged 15 min idle / 8 h, tenants 30 min / 12 h
    - _Requirements: 20, 21; closes DEV-11, DEV-28_
  - [ ]* 5.16 Write integration tests against the Auth0 test tenant: login, two audiences, step-up, Management API isolation, SSO
    - _Requirements: 19, 20, 21, 24, 25, 26, 27_
  - [ ] 5.17 Close Stage 2: enable Stage 2 flags, delete replaced MVP paths, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 6. Checkpoint - Stage 2
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Stage 3: Separate deployables and internal trust
  - [ ] 7.1 Split the Gateway process into the nine deployables on Compose
    - `infra/docker/service.Dockerfile` with a target per service; per-service DB role, DSN and credentials; networks `edge`, `control`, `data`, `ops`, `stores` with no store host ports outside local (pending Q-02, Q-40); pooled stores by default with a per-organization silo setting
    - _Requirements: 29, 40, 83, 84; closes DEV-01_
  - [ ] 7.2 Remove the `gateway` exclusion from the import-linter contract and add contracts: no Qdrant client outside `lmqa_vectorstore`, no generative LLM client in the Validator
    - _Requirements: 84_
  - [ ] 7.3 Context tokens and signer certificates in `lmqa_auth`
    - `ContextTokenMinter.mint` from `principal_v` (`scope_hash`, `scope_version`, `pv`, `auth_strength`); KMS trust root and signer certificates; 60 s lifetime; `jti` replay store in Valkey for state-changing calls
    - _Requirements: 28.1, 28.3; closes DEV-12 (token part)_
  - [ ]* 7.4 Write property test for context tokens
    - **Property 20: Context token round trip and rejection**
    - **Validates: Requirements 28.1, 28.3**
  - [ ] 7.5 Gateway token verification: check `azp`, `org_id` against the active membership, deny and alert on role-claim mismatch (Q-10)
    - _Requirements: 22; closes DEV-30_
  - [ ] 7.6 Replace the in-process `Services` object with HTTP clients that send a Context_Token per call; Gateway DB access limited to `principal_v` and `audit_append`; scope taken only from the verified token and the database
    - _Requirements: 1.10, 28; closes DEV-12_
  - [ ]* 7.7 Write property test for scope injection
    - **Property 6: Scope comes only from the verified token and the database**
    - **Validates: Requirements 1.10**
  - [ ] 7.8 §15 API paths
    - Rename routes to §15; matrix, `contracts/openapi/` and code drift checked at start and in CI; unlisted role or out-of-scope ID returns 404 identical to missing; status codes per Q-24 and Q-25
    - _Requirements: 2.2, 2.3, 2.6, 2.7, 70, 71, 72, 73, 74, 75, 76, 77; closes DEV-26_
  - [ ]* 7.9 Write property test for indistinguishable 404s
    - **Property 8: Forbidden and out-of-scope answers are indistinguishable from missing**
    - **Validates: Requirements 2.2, 2.6, 2.7**
  - [ ] 7.10 Valkey rate limits, hierarchical quotas (organization, workspace, user) and idempotency keys in the Gateway
    - _Requirements: 64, 70; closes DEV-27_
  - [ ]* 7.11 Write property test for idempotency
    - **Property 39: Idempotent state-changing calls**
    - **Validates: Requirements 70**
  - [ ]* 7.12 Write property test for hierarchical quotas
    - **Property 40: Hierarchical quotas**
    - **Validates: Requirements 64**
  - [ ] 7.13 Revocation pub/sub subscriber that closes open streams, with the 5 s / 15 s fallback; `GET /v1/health` returns liveness only; fail closed when KMS, Valkey, Qdrant or PostgreSQL is down
    - _Requirements: 23, 34; closes DEV-39_
  - [ ]* 7.14 Write contract and integration tests: Schemathesis over `contracts/openapi/`, revocation SLO, open-stream cut, fail-closed with dependencies stopped
    - _Requirements: 23, 34, 70, 71, 72, 73, 74, 75, 76, 77_
  - [ ] 7.15 Close Stage 3: enable Stage 3 flags, delete the in-process wiring, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 8. Checkpoint - Stage 3
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Stage 4: Ingestion, objects, embeddings and index consistency
  - [ ] 9.1 `lmqa_objectstore` S3 adapter (SeaweedFS locally) replacing local disk; per-document key encryption; quarantine prefix; `presign_put`, `get`, `promote`
    - _Requirements: 52; closes DEV-09 (objects)_
  - [ ]* 9.2 Extend the Property 31 test to objects
    - **Property 31: Encryption round trip and scope binding** (object case)
    - **Validates: Requirements 52**
  - [ ] 9.3 Two-step presigned upload owned by ingestion into the quarantine prefix; remove storage access from the Gateway
    - _Requirements: 41; closes DEV-22_
  - [ ] 9.4 Procrastinate worker with signed job envelopes and fair-share slots, replacing the `Ingestor` thread pool
    - _Requirements: 30, 38; closes DEV-23_
  - [ ]* 9.5 Write property test for job envelopes
    - **Property 21: Job envelope integrity**
    - **Validates: Requirements 30**
  - [ ] 9.6 Document lifecycle `uploading → scanning → parsing → (ocr_review) → indexing → indexed` with side exits; ClamAV and OCR enabled; malware to `quarantined`, low OCR confidence to `ocr_review`
    - _Requirements: 41, 42; closes DEV-20, DEV-24_
  - [ ] 9.7 Token-based chunker (40 / 300 to 700 / 1,200) with §11.2 chunk kinds, page range, section and span
    - _Requirements: 43; closes DEV-25_
  - [ ] 9.8 Self-hosted embedding adapter as default in `lmqa_vectorstore` (pending Q-06); third-party provider only when the organization configures it; `embedding_cache` keyed by `(org_id, workspace_id, model, text_sha256)`
    - _Requirements: 33, 38, 50; closes DEV-03, DEV-04_
  - [ ]* 9.9 Write property test for scoped keys and payloads
    - **Property 5: Every key and payload carries its scope**
    - **Validates: Requirements 1.2, 33, 38**
  - [ ] 9.10 `index_outbox` trigger in the same transaction as scope changes; indexer and reconciler on Qdrant through `lmqa_vectorstore.update_payload` and `delete_by_filter`
    - _Requirements: 36.1, 36.2, 36.4_
  - [ ]* 9.11 Write property test for outbox and reconciler convergence
    - **Property 36: Outbox and reconciler converge to PostgreSQL**
    - **Validates: Requirements 36.1, 36.2, 36.4**
  - [ ]* 9.12 Write property test for walls
    - **Property 10: Walls change scope, not content**
    - **Validates: Requirements 6.4, 6.10**
  - [ ]* 9.13 Write unit tests for quarantine, OCR thresholds and chunk kinds
    - _Requirements: 41, 42, 43_
  - [ ] 9.14 Close Stage 4: enable Stage 4 flags, delete the thread pool and local-disk paths, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 10. Checkpoint - Stage 4
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Stage 5: Retrieval on Qdrant and the retrieval ledger
  - [ ] 11.1 `lmqa_vectorstore.build_filter(principal)` mirroring rules 1 to 8, always constraining `org_id` and `workspace_id`, excluding walled matters, raising `NoFilter`; the >256-grant fallback (pending Q-07)
    - _Requirements: 4.4, 6.3, 35.2, 35.6_
  - [ ]* 11.2 Write property test for the vector filter
    - **Property 2: Vector filter is a superset of RLS and excludes walls**
    - **Validates: Requirements 4.4, 6.3, 35.2**
  - [ ] 11.3 Retrieval service on Qdrant
    - Candidates via `build_filter`; re-fetch under RLS, drop refused IDs and count the mismatch; sole writer of `retrieval_records` with request-local aliases; 403 on `NoFilter`; remove ledger writes from the Gateway; pgvector kept only as the ADR 0004 fallback
    - _Requirements: 31, 35.4, 36.3, 44; closes DEV-02, DEV-46_
  - [ ]* 11.4 Write property test for retrieval output
    - **Property 3: Retrieval output is a subset of RLS**
    - **Validates: Requirements 35.4, 36.3, 44**
  - [ ]* 11.5 Write unit tests for the >256-grant fallback and the 403 on `NoFilter`
    - _Requirements: 35_
  - [ ] 11.6 Close Stage 5: enable Stage 5 flags, delete the pgvector request path, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 12. Checkpoint - Stage 5
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Stage 6: Generation, prompt protocol, budgets and cache
  - [ ] 13.1 `[chunk_N]` citation tag formatter and parser as one shared module; prompt templates use aliases `chunk_1..n` (pending Q-12)
    - _Requirements: 46, 47.1; closes DEV-07_
  - [ ]* 13.2 Write property test for the tag grammar
    - **Property 23: Citation tag grammar round trip**
    - **Validates: Requirements 46, 47.1**
  - [ ] 13.3 Generation reads ledger and chunks under RLS and puts only request-local aliases in prompts
    - _Requirements: 31.2, 31.4_
  - [ ]* 13.4 Write property test for ledger isolation
    - **Property 22: Ledger isolation and aliases**
    - **Validates: Requirements 31.2, 31.4**
  - [ ] 13.5 Provider tokenizer counts and guarded compression; per-organization provider, key and budget; 1,500-token output cap; no cross-provider fallback unless configured; remove global `LLM_FALLBACK_MODELS`
    - _Requirements: 45, 50; closes DEV-31, DEV-32_
  - [ ]* 13.6 Write property test for the token budget
    - **Property 38: Token budget**
    - **Validates: Requirements 45**
  - [ ] 13.7 Scoped semantic answer cache keyed by scope hash
    - _Requirements: 37_
  - [ ]* 13.8 Write property test for the answer cache
    - **Property 37: Scoped answer cache**
    - **Validates: Requirements 37**
  - [ ] 13.9 Remove the `entailment` and `plan_query` LLM calls from the query path; prompt and model lifecycle (versioned, pinned); prompt-injection controls
    - _Requirements: 39, 49_
  - [ ]* 13.10 Write live-model prompt-injection tests with floors in `eval/floors.toml`
    - _Requirements: 39_
  - [ ] 13.11 Close Stage 6: enable Stage 6 flags, delete `[S1]` tags and estimated token counts, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 14. Checkpoint - Stage 6
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Stage 7: Deterministic validator and gated delivery
  - [ ] 15.1 Validator V1 to V8 only (pending Q-13)
    - V1 `[chunk_N]` grammar; V2 ledger membership; V3 content hash; V4 uncited claims; V5 normalizer for units, thousands separators and dates; V6 pinned ONNX NLI (weights hash, CPU, fixed batch size, threshold from `eval/floors.toml`); V7 canonical refusal; V8 tag resolution; remove the Q and L checks and the LLM entailment pass
    - _Requirements: 43, 47, 100; closes DEV-05, DEV-06_
  - [ ]* 15.2 Write property test for ledger binding
    - **Property 24: Citations bind to the ledger**
    - **Validates: Requirements 47.2, 47.3, 47.8, 43**
  - [ ]* 15.3 Write property test for numeric fidelity
    - **Property 25: Numeric fidelity under normalization**
    - **Validates: Requirements 47.5**
  - [ ]* 15.4 Write property test for uncited claims and refusals
    - **Property 26: Uncited claims and refusals**
    - **Validates: Requirements 47.4, 47.7, 100**
  - [ ]* 15.5 Write property test for validator determinism
    - **Property 27: Validator determinism**
    - **Validates: Requirements 47.9**
  - [ ] 15.6 Sign verdicts with the KMS-certified ephemeral key over (`request_id`, `sentence_sha256`, `outcome`, `checks`)
    - _Requirements: 48.1_
  - [ ] 15.7 Gateway `sentence_gated` delivery as default
    - `query_flow.py` becomes an orchestrator over HTTP clients; forward deltas to the Validator; release a sentence only with a verified passing Verdict after `segment.released` commits; strip marker on failure; `buffered` only with `regenerate` (2 retries); `query.completed` with sealed payload; abort on audit failure or `pv` mismatch
    - _Requirements: 48.1, 48.2, 48.3, 48.4, 48.5, 48.6, 48.7, 48.8; closes DEV-08_
  - [ ]* 15.8 Write property test for gated release
    - **Property 28: Only signed passing sentences are released**
    - **Validates: Requirements 48.1, 48.3, 48.4, 48.5, 48.6**
  - [ ]* 15.9 Write property test for write-ahead audit
    - **Property 29: Write-ahead audit**
    - **Validates: Requirements 48.7, 48.8**
  - [ ] 15.10 SSE serializer and `Last-Event-ID` resume buffer in Valkey
    - _Requirements: 48.9, 48.10_
  - [ ]* 15.11 Write property test for SSE round trip and resume (Python against the Gateway serializer; `fast-check` pending Q-38)
    - **Property 30: SSE round trip and resume**
    - **Validates: Requirements 48.9, 48.10, 82**
  - [ ]* 15.12 Write live NLI calibration tests on human-labeled pairs with floors in `eval/floors.toml`
    - _Requirements: 47.11_
  - [ ] 15.13 Close Stage 7: enable Stage 7 flags, delete whole-answer in-process validation, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 16. Checkpoint - Stage 7
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 17. Stage 8: Frontend
  - [ ] 17.1 Replace custom SSE parsing with `eventsource-parser` (Q-17) and add a typed client from `openapi-typescript` plus `openapi-fetch`
    - _Requirements: 80, 82; closes DEV-34 (client part)_
  - [ ] 17.2 Adopt shadcn/ui and implement the §17.1 route table and role routing, including key surfaces
    - _Requirements: 80, 81_
  - [ ] 17.3 Strict CSP without `unsafe-inline`, Trusted Types, no inline scripts; invite codes in the URL fragment; `Referrer-Policy: no-referrer`
    - _Requirements: 16.9, 82; closes DEV-34_
  - [ ]* 17.4 Write Playwright tests for role routing, CSP, streaming torture cases, the browser SSE parser and accessibility
    - _Requirements: 80, 81, 82_
  - [ ] 17.5 Close Stage 8: enable Stage 8 flags, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 18. Checkpoint - Stage 8
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 19. Stage 9: Governance, operator plane, audit service and key lifecycle
  - [ ] 19.1 Governance requests with two-person approval, step-up, waiting windows, expiry and sealing; KeyGuard as the only disable or destroy path
    - _Requirements: 3.6, 54, 55, 73_
  - [ ]* 19.2 Write property test for governance requests
    - **Property 18: Governance requests respect two persons and windows**
    - **Validates: Requirements 3.6, 54, 55**
  - [ ] 19.3 Successor transfer and owner recovery effects registered in `worker.build`
    - _Requirements: 18, 69; closes DEV-19_
  - [ ] 19.4 Ops service on its own ingress and identity provider: operator roles, JIT access types and limits, prohibitions, reaching identity only through the internal API
    - _Requirements: 66, 67, 68, 76_
  - [ ] 19.5 Audit service reads with read scopes; audit-anchor writes the hourly Merkle root of chain heads to the Object Lock bucket with inclusion proofs
    - _Requirements: 61.3, 62_
  - [ ]* 19.6 Write property test for anchoring
    - **Property 34: Anchor root covers all chain heads**
    - **Validates: Requirements 61.3**
  - [ ] 19.7 Retention worker, shredding and tombstone ledger, organization destruction ritual, backup, restore and escrow drills as automated jobs
    - _Requirements: 56, 57, 58, 61_
  - [ ] 19.8 Detection signals and alert rules
    - _Requirements: 63_
  - [ ]* 19.9 Write unit and example tests for wall lift, successor transfer, owner recovery, notifications and the destruction ritual
    - _Requirements: 6, 18, 56, 69_
  - [ ] 19.10 Close Stage 9: enable Stage 9 flags, attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 20. Checkpoint - Stage 9
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 21. Stages 10 and 11: Verification suites
  - [ ] 21.1 Isolation suite across every output channel (responses, SSE, cache, logs, audit, errors)
    - _Requirements: 95_
  - [ ] 21.2 k6 load test scripts for the §20 budgets
    - _Requirements: 96_
  - [ ] 21.3 Chaos tests that stop real dependencies and revoke keys, plus recurring-control checks
    - _Requirements: 34, 97_
  - [ ] 21.4 Evaluation sets from the corpus and floors in `eval/floors.toml`
    - _Requirements: 98, 100_
  - [ ] 21.5 Configuration catalog and a check for production policy minimums
    - _Requirements: 99_
  - [ ] 21.6 Close Stages 10 and 11: attest twice and advance `STAGE`
    - _Requirements: 93, 94_

- [ ] 22. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; the gates for a stage may still require some of them.
- All 40 design properties have a property test sub-task; Property 31 has a second sub-task (9.2) for the object case.
- DEV-15 is closed in Stage 1 with the access rules; the design's stage table does not list it.
- DEV-21 stays open until Q-04 is answered (task 3.6 only freezes the features).
- R-65 (compliance mapping for counsel review) and the external validation and counsel sign-off in Stages 10 and 11 are not coding work and have no task.
- Tasks that say "pending Q-xx" build the v3.1 default; an answer that differs changes that task before it starts.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.9"] },
    { "id": 2, "tasks": ["1.8"] },
    { "id": 3, "tasks": ["1.10"] },
    { "id": 4, "tasks": ["1.11"] },
    { "id": 5, "tasks": ["2"] },
    { "id": 6, "tasks": ["3.1", "3.5", "3.9"] },
    { "id": 7, "tasks": ["3.2", "3.18"] },
    { "id": 8, "tasks": ["3.3", "3.13"] },
    { "id": 9, "tasks": ["3.4", "3.14"] },
    { "id": 10, "tasks": ["3.6", "3.10", "3.11", "3.12"] },
    { "id": 11, "tasks": ["3.7"] },
    { "id": 12, "tasks": ["3.8", "3.15"] },
    { "id": 13, "tasks": ["3.16", "3.17", "3.19"] },
    { "id": 14, "tasks": ["3.20"] },
    { "id": 15, "tasks": ["4"] },
    { "id": 16, "tasks": ["5.1", "5.2", "5.3", "5.13", "5.15"] },
    { "id": 17, "tasks": ["5.4", "5.5", "5.6", "5.14"] },
    { "id": 18, "tasks": ["5.7", "5.8", "5.10"] },
    { "id": 19, "tasks": ["5.9", "5.11"] },
    { "id": 20, "tasks": ["5.12", "5.16"] },
    { "id": 21, "tasks": ["5.17"] },
    { "id": 22, "tasks": ["6"] },
    { "id": 23, "tasks": ["7.1", "7.2", "7.3", "7.5"] },
    { "id": 24, "tasks": ["7.4", "7.6"] },
    { "id": 25, "tasks": ["7.7", "7.8"] },
    { "id": 26, "tasks": ["7.9", "7.10"] },
    { "id": 27, "tasks": ["7.11", "7.12", "7.13"] },
    { "id": 28, "tasks": ["7.14"] },
    { "id": 29, "tasks": ["7.15"] },
    { "id": 30, "tasks": ["8"] },
    { "id": 31, "tasks": ["9.1", "9.4", "9.7"] },
    { "id": 32, "tasks": ["9.2", "9.3", "9.5", "9.8"] },
    { "id": 33, "tasks": ["9.6", "9.9"] },
    { "id": 34, "tasks": ["9.10", "9.13"] },
    { "id": 35, "tasks": ["9.11", "9.12"] },
    { "id": 36, "tasks": ["9.14"] },
    { "id": 37, "tasks": ["10"] },
    { "id": 38, "tasks": ["11.1"] },
    { "id": 39, "tasks": ["11.2", "11.3"] },
    { "id": 40, "tasks": ["11.4", "11.5"] },
    { "id": 41, "tasks": ["11.6"] },
    { "id": 42, "tasks": ["12"] },
    { "id": 43, "tasks": ["13.1", "13.5", "13.7"] },
    { "id": 44, "tasks": ["13.2", "13.3", "13.6", "13.8"] },
    { "id": 45, "tasks": ["13.4", "13.9"] },
    { "id": 46, "tasks": ["13.10"] },
    { "id": 47, "tasks": ["13.11"] },
    { "id": 48, "tasks": ["14"] },
    { "id": 49, "tasks": ["15.1"] },
    { "id": 50, "tasks": ["15.2", "15.3", "15.4", "15.5", "15.6"] },
    { "id": 51, "tasks": ["15.7", "15.12"] },
    { "id": 52, "tasks": ["15.8", "15.9", "15.10"] },
    { "id": 53, "tasks": ["15.11"] },
    { "id": 54, "tasks": ["15.13"] },
    { "id": 55, "tasks": ["16"] },
    { "id": 56, "tasks": ["17.1", "17.3"] },
    { "id": 57, "tasks": ["17.2"] },
    { "id": 58, "tasks": ["17.4"] },
    { "id": 59, "tasks": ["17.5"] },
    { "id": 60, "tasks": ["18"] },
    { "id": 61, "tasks": ["19.1", "19.4", "19.5"] },
    { "id": 62, "tasks": ["19.2", "19.3", "19.6", "19.8"] },
    { "id": 63, "tasks": ["19.7"] },
    { "id": 64, "tasks": ["19.9"] },
    { "id": 65, "tasks": ["19.10"] },
    { "id": 66, "tasks": ["20"] },
    { "id": 67, "tasks": ["21.1", "21.2", "21.3", "21.4", "21.5"] },
    { "id": 68, "tasks": ["21.6"] },
    { "id": 69, "tasks": ["22"] }
  ]
}
```
