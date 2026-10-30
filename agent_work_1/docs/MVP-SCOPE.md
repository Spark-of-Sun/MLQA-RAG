# MVP scope: what is in, what is deferred, and what was changed from the document

The architecture document describes twelve gated stages, 29 sections and a defect register of 64 items. It also
refers to a companion "MVP Prototype Report and Process" that was **not supplied**. So the MVP scope below is my own
reading of the document's `mvp` gate profile ("may reduce sizes and feature scope but never a safety threshold").
Please check it matches what you meant.

## In the MVP (built and tested model-free)

* The full data layer: schema, row-level security for the eight-rule access decision, roles and grants, composite foreign
  keys, generated state machines, hash-chained insert-only audit.
* Keys: envelope encryption, per-document / workspace / organization hierarchy, OpenBao and AWS KMS adapters, KeyGuard.
* Identity: organizations, the three onboarding paths, join codes, approvals, suspension cascades, matters, grants,
  ethical walls, workspace policy.
* Gateway: Auth0 token verification, database principals, allow-list from the authorization matrix, step-up, rate limits,
  idempotency, context tokens, revocation, resume buffer, the sentence-gated query flow.
* Ingestion (PDF, HTML, JATS, SPL, eCFR, DOCX, text), structure-aware chunking, scanning, encryption, indexing, deletion
  by crypto-erase, access changes through an outbox.
* Retrieval (hybrid, PostgreSQL cross-check), generation (token budget, prompt, cache, provider-agnostic client),
  validator (V1-V8, signed verdicts), audit service.
* Frontend, infrastructure as code (AWS, Cloudflare, Auth0, Kubernetes, Compose), CI, runbooks, ADRs.

## Deferred, by design (feature flags in `contracts/features.toml`; their routes answer 404)

Governance requests (successor transfer, wall lift, unseal, destroy, owner recovery, co-owner); break-glass and
clinical emergency access **APIs** (the database rules for them exist and are tested); the operator plane and JIT
access; exports; the held-documents queue; the citation side-panel endpoint; the authenticators endpoint; audit
monthly partitioning and checkpoint records; quotas; the OCR engine and OCR review screen; prompt compression;
re-embedding by alias swap; the reconciler job and the nightly drift repair; the audit anchor job (written, needs AWS
Object Lock); generated TypeScript client.

## Changed from the document (all in `DEVIATIONS.md` with the reason)

One `access_sessions` table for break-glass, emergency and operator access; a shared Dockerfile instead of eight; hand-written
frontend API client; TypeScript 6.0.3 instead of the newest; ingestion as an in-process background task instead of
Procrastinate (spike G0.13 not run); small default ML models so the build could run them at all; corpus of 12 documents
instead of 150 + 150.

## Honest size of the gap to production

The document's own estimate is twelve stages including an external penetration test, counsel sign-off and vendor
agreements. This MVP covers the build of stages 0 to 7 (model-free half), a first version of stage 8, and the *code* for
stage 11's infrastructure. It is a strong foundation, not a finished product.
