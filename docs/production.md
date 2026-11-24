# Production build: what is written, what is switched on, what is proven

The production build follows the blueprint stage by stage on top of the MVP (docs/mvp.md). Every MVP flow keeps
working unchanged: new schema is additive, and each production capability sits behind a flag in
`contracts/features.toml` that stays off until the gates bound to it pass (`make gate`). A disabled feature's
routes answer 404. `FEATURE_<NAME>=on` enables one locally for development; it is ignored when `APP_ENV=production`.

**Status: code written, not yet tested.** Only the Stage 0 infrastructure, toolchain and queue-spike suites have run
(see "Verified" below). Migrations 0006 to 0008 have not been applied to any database yet. Run the test phase
before relying on anything listed under "Written".

## Verified

| Gate | Evidence |
| --- | --- |
| G0.4 | `tests/integration/test_stage0_infra.py`: 22 passed (before the production code was added). Containers healthy, server versions match docs/versions.md, PgBouncer keeps context transaction-local and supports prepared statements, Valkey ACL users per service, Qdrant read-only vs read-write keys, SeaweedFS capability probe passed (versioning, presigned PUT/GET and expiry, multipart, SHA-256 checksums, scoped credentials), OpenBao Transit round trip and destruction |
| G0.13 | `tests/integration/test_stage0_queue_spike.py`: 4 passed. Procrastinate defer through PgBouncer is transactional, slot locks bound per-workspace concurrency, NOTIFY reaches a direct-connection worker, throughput meets the floor (ADR 0011) |
| G0.1, G0.5, G0.6, G0.10, G0.11 | `tests/contract/test_stage0_toolchain.py`: last run 27 passed, 2 failed (an unpinned ClamAV image and a too-broad secret-name check). Both were fixed afterwards but the suite was not re-run. Still open: the `observability` image is not pinned by digest (its pull failed), so the digest test will fail until it is pulled and pinned. The suite ran before the ADRs existed and before the later code |
| Static | `ruff check` and `ruff format --check` clean; `lint-imports` 7 contracts kept; `tsc --noEmit` clean; every Python module imports; `create_app()` builds with all production routes and no authz-matrix drift |

## Written (untested)

| Stage | Code |
| --- | --- |
| 0 | `compose.yaml` (PostgreSQL 18, PgBouncer, Valkey, Qdrant, SeaweedFS, OpenBao; ClamAV and observability profiles), `tools/infra_config.py`, `tools/gatekeeper.py` + `stages.toml` + `STAGE`, `tools/gen_versions.py`, `tools/export_openapi.py`, `tools/auth_harness.py`, `make up/gate/advance/paths/versions/contracts/test`, ADRs 0001 to 0012, `.env.example` |
| 1 | `db/migrations/0006_production_core.sql` (matters, grants, walls, emergency exceptions, break-glass, key tables, outbox, tombstones, idempotency, quotas, usage, governance, sealed audit, operator schema); `db/policies/11_access.sql` (the single access decision `app_can_read`, scope hash and principal-version triggers, outbox trigger, `principal_v`, `app_vector_scope`); `15_force_rls.sql` (FORCE RLS everywhere, boot self-test); `31_audit_sealed.sql` (sealed append, checkpoints, anchor leaves); `40_transitions.sql` generated from `contracts/state-machines.yaml`; per-service roles and grants; `lmqa_keys` (AWS KMS and OpenBao providers, envelope and streaming AES-GCM, key ring with DEK cache, escrow and sealing, KeyGuard authorization, responder and policy lint); `lmqa_security.sealing` (HPKE); `lmqa_audit.sealed`; `lmqa_db.ServiceDatabase`, `OrgRouter`; `lmqa_testing.oracle`; `infra/keyguard`, `infra/aws` |
| 2 | `identity.auth0_mgmt` (scoped Management API client), `identity.saga` (organization provisioning with compensation), `identity.governance` (two-person requests), `identity.scope_admin` (matters, grants, walls, emergency access, break-glass, reviews), `identity.lifecycle` (revocation fan-out, notifications outbox and SMTP, cascades, successor transfer, Auth0 reconciliation), `identity.worker`, `lmqa_models.policy` (policy values and production lint), `infra/auth0` (OpenTofu, post-login Action), `contracts/claims` |
| 3 | `lmqa_auth.context` (signer certificates, context tokens, replay cache, signed job envelopes), `lmqa_auth.internal`, `gateway.trust` (principal cache, revocation consumer, Valkey rate limits with local fallback, idempotency, RFC 9470 step-up), feature-flag and step-up enforcement in the route guard, `gateway.production` routes |
| 4 | `lmqa_objectstore.s3` (presigned quarantine uploads, encrypted originals), `ingestion.scan` (ClamAV, PDF active-content removal), `ingestion.ocr` (pypdfium2 + Tesseract with confidence), `ingestion.production` (Procrastinate worker with slot locks and envelopes, indexer, reconciler, crypto-erase) |
| 5 | `lmqa_vectorstore.qdrant` (scope filter builder, read-only reader, read-write writer), `lmqa_vectorstore.sparse`, `retrieval.vector_search` and the Qdrant path in `RetrievalService` |
| 6 | `generation.streaming` (budgeted prompt, provider streaming for Gemini, OpenAI-compatible and Anthropic, cancellation), `generation.cache` (scoped encrypted answer cache), `prompts/templates/answer_stream.md` |
| 7 | `citation_validator.streaming` (legal/medical-aware segmenter, per-sentence validation, signed verdicts), `citation_validator.nli` (pinned ONNX NLI for V6), `gateway.stream` (sentence-gated SSE with write-ahead audit and resume), `db/migrations/0008_streaming_release.sql` |
| 8 | Valkey session store, SSE parser and stream client, streaming chat, matters and walls, review queue, governance center, step-up redirect, BFF header pass-through, ESLint flat config, Vitest config |
| 9 | `audit.anchor` (Merkle anchors to Object Lock, sealed payload reader, month shredding, tombstone mirror and replay), `audit.alerts`, `audit.worker`, `identity.destruction` (organization ritual, workspace seal/unseal/destroy, retention clock), `gateway.quotas`, `ops` service (JIT access, KeyGuard approvals), runbooks |

## Not done

* Test suites for stages 1 to 10 (the next phase), including the 20,000-scenario RLS oracle comparison (G1.4).
* Kubernetes, CI/CD workflows and Stage 11 production infrastructure: skipped at the owner's request.
* Splitting the services into separate deployables: the internal-call verifier (`lmqa_auth.internal`) and the
  container image exist; the gateway still calls the services in one process (MVP deviation 1).
* ruff `select = ["ALL"]` at line length 100 (G0.2) and pyright strict (G0.3): about 1,700 existing findings.
* ESLint: 44 findings remain in existing frontend code (mostly promise-returning handlers and non-null assertions).
* Corpus expansion to the G0.8 minimums (150 legal and 150 medical documents).
* External prerequisites: AWS dev account and KMS trust root, Object Lock buckets, Auth0 Organizations and the
  OpenTofu-managed tenant, a test mailbox (IMAP/SMTP), an on-call webhook, and the operator identity provider.
