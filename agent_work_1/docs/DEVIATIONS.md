# Deviations from the architecture document

Every place the build differs from the document, and why. Anything not listed here follows the document.

| # | Document says | Build does | Reason |
| --- | --- | --- | --- |
| 1 | Separate `break_glass_sessions` and `access_exceptions` tables (16.2) | One `access_sessions` table with a `kind` column | Section 6.8 says they share one lifecycle; one state machine is declared in `state-machines.yaml` |
| 2 | Twelve gated stages, `full` profile | `mvp` profile; model-free half of stages 0 to 7, first stage 8, IaC for stage 11 | The companion MVP report was not supplied; see `MVP-SCOPE.md` |
| 3 | Eight Dockerfiles, one per service | One shared `infra/docker/service.Dockerfile` with build args | Identical recipe; one place to fix. Never built (no Docker here) |
| 4 | Generated TypeScript client from OpenAPI (17.3) | Hand-written `lib/api-client.ts`; OpenAPI exported to `contracts/openapi` and drift-tested against the matrix | The exported documents are the internal service APIs; the public API is the matrix. Generating a client is a small follow-up |
| 5 | `proxy.ts` calls `/me` and routes by role (17.1) | `proxy.ts` mounts Auth0, sets the CSP and gates anonymous visitors; role routing is in server layouts via `requireMe` | A database round trip on every asset request would be wasteful; the control is the Gateway either way |
| 6 | Idle 15 min / absolute 8 h for privileged, 30 min / 12 h for tenants (8.4) | The strictest (privileged) limits for everyone | The SDK has one setting; per-role tuning is a later refinement |
| 7 | Procrastinate queue with direct worker connections (D18) | Ingestion completes as an in-process background task; re-index work goes through a transactional outbox | Spike G0.13 was not run; ADR 0011 is "Proposed" |
| 8 | bge-m3 / bge-reranker-v2-m3 / a DeBERTa-v3 NLI model (4.5) | Small defaults: bge-small, a MiniLM cross-encoder, nli-deberta-v3-small. Names are configuration | They had to run at all on this machine. The bake-offs (G4.6, G5.3, G7.3) were not done |
| 9 | Calibrated thresholds from labelled data (G7.3, G5.11) | `NLI_THRESHOLD`, `RERANK_THRESHOLD` default to flagged placeholders; start-up logs the fact | I have no human-labelled data (rule R10) and will not guess a precision floor |
| 10 | At least 150 legal + 150 medical documents, 30 scanned, DOCX items (G0.8) | 12 real public documents with licence and SHA-256 | MVP size; the fetcher and manifest are the real mechanism |
| 11 | Remove active content from PDFs (11.1) | Reject a PDF that contains it | Safer and simpler; sanitizing is later work |
| 12 | OCR with Tesseract and a review UI (11.1) | A page with no text layer is flagged `extraction=none`, the document goes to `ocr_review`, and **nothing is searchable** | Tesseract is not installed and no review UI exists; the safe behaviour (quarantine, never embed) is implemented |
| 13 | `domain_allowlist` join policy (7.4) | Treated as `manual` | Needs verified email domains |
| 14 | Join preview shows the admin's display name (7.4) | Shows a neutral workspace label | Names are not stored in the clear in the MVP |
| 15 | Valkey ACL user per service (9.2) | Supported, optional, left as placeholders locally | A local Valkey has no ACL users; a placeholder counts as "not configured" |
| 16 | Local key provider OpenBao (12.10) | OpenBao in dev mode (`local-keys` compose profile) | Fast shredding tests. **Never use dev mode with real data** |
| 17 | One least-privilege IAM role per service | Also a `single_host` mode: one EC2 role for all services | Lets a first staging run work without EKS. A documented privilege compromise; destruction of keys is still impossible |
| 18 | Node.js 24 LTS | Frontend built here on Node 20.20; the Dockerfile uses Node 24 | The sandbox's Node. `engines` is `>=20.9` |
| 19 | TypeScript newest | TypeScript 6.0.3 | `typescript-eslint` does not support TypeScript 7 yet |
| 20 | Gateway resume key from the key hierarchy | A service secret `GATEWAY_RESUME_KEY` | The Gateway must hold no key that decrypts stored content; the buffer is transient (10 minutes) |
| 21 | Audit anchoring job with a Merkle root (13.3) | `Anchorer` and `merkle_root` written, **never run** | Needs real S3 Object Lock |
| 22 | Reconciler job and drift repair (10.6) | Not built; the outbox covers access changes | Deferred |
| 23 | Stage attestation signed with cosign (19.6) | `tools/gatekeeper.py` writes an unsigned JSON; the workflow signs it | Signing needs CI identity |
