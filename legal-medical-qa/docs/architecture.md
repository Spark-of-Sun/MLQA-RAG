# Architecture: where the design lives in the code

The design (the 29-section architecture document) is the specification. This table shows where each part is
implemented and which test proves it. "Deferred" means not built in this MVP (see `STATUS.md` and
`contracts/features.toml`).

| Design topic (section) | Implementation | Proven by |
| --- | --- | --- |
| Access decision, 8 ordered rules (5.4) | `db/policies/030_context.sql` `app_can_access`, oracle `libs/lmqa_models/access.py` | `test_policy_equals_oracle.py`: RLS equals the oracle on 260 random worlds; 7 injected policy bugs all detected |
| Fail closed with `NULLIF` (10.3, DEF-52) | `db/policies/030_context.sql`, `lmqa_db` | `test_fail_closed.py` (reused pooled connection), `test_pooler_safety.py` (10,000 interleaved transactions on real PgBouncer) |
| Super Admin boundary (5.3) | no policy on content tables for the role; no route in `contracts/authz-matrix.yaml` | `test_super_admin_boundary.py`, `test_authz_matrix.py` |
| State machines as data (6) | `contracts/state-machines.yaml` -> generated triggers (`lmqa_models/state_machine.py`) | every ordered state pair against the real triggers (`test_db_state_machines.py`) |
| Key hierarchy, shredding (12) | `libs/lmqa_keys` (envelope, KeyService, OpenBao + AWS KMS adapters) | `test_key_service_openbao.py` (real OpenBao); AWS KMS test written, **not run** |
| KeyGuard (12.5) | `kms_key_policy` on every runtime key, `infra/aws/kms.tf`, `infra/keyguard/` | `test_aws_kms_live.py` (policy shape), `test_keyguard_lint.py` |
| Join codes (7.6) | `libs/lmqa_security/codes.py`, `services/identity/codes.py` | `test_codes.py`, `test_identity.py` (uniform rejection, rate limits, timing) |
| Sealed audit + hash chain (13) | `db/policies/070_audit.sql`, `libs/lmqa_audit` (HPKE) | `test_audit.py` (tamper detected at the exact event), `test_audit_client.py` |
| Context tokens + certificates (9.1) | `libs/lmqa_auth/context.py` | `test_context_tokens.py` (real OpenBao trust root, real Valkey) |
| Token verification (8.5) | `libs/lmqa_auth/tokens.py` | `test_tokens.py` (alg=none, HS256 confusion, wrong aud/iss, ...) |
| Ingestion (11.1, 11.2) | `services/ingestion` (parsers, chunker, scanner, pipeline) | `test_chunking_corpus.py` (12 real documents), `test_pipeline_e2e.py` (**needs a model**, not run in the final build) |
| Retrieval, vector filter (10.5, 11.3) | `libs/lmqa_vectorstore`, `services/retrieval` | `test_vector_vs_rls.py` (filter contains RLS result), `test_retrieval_e2e.py` (**needs a model**) |
| Generation, token budget, cache (11.4, 10.7) | `services/generation` | `test_budget_prompt.py`, `test_generation_cache.py` |
| Validator V1-V8, signed verdicts (11.6) | `services/citation_validator` | `test_validator_e2e.py` (20 model-free), NLI path **not run** |
| Gated release, write-ahead audit (4.4) | `services/gateway/query.py` | gateway e2e covers failure paths; the **full gated release was not run end to end** |
| Gateway: allow-list, principals, revocation (8.6) | `services/gateway` | `test_gateway_e2e.py` (12 tests incl. 2 s revocation) |
| Frontend (17) | `frontend/` | Vitest (SSE sliced at every byte), `next build`; no browser tests |
| Infra as code | `infra/aws`, `infra/cloudflare`, `infra/auth0` | `tofu validate`; **never applied** |

## Request path

1. Browser -> frontend (BFF). The browser holds an opaque session cookie only; the BFF holds the Auth0 token.
2. BFF -> Gateway with the Auth0 token. The Gateway verifies it, resolves the principal from PostgreSQL, checks the
   allow-list, step-up and rate limits, then mints a one-audience 60 second **context token** for each service it calls.
3. `/v1/query`: write-ahead audit -> retrieval (a ledger row; chunk text never travels through the Gateway) -> generation
   streams *unverified* text -> the validator segments it and signs a verdict per sentence -> the Gateway releases a
   sentence only for a valid verdict, after committing `segment.released`.

## Honest limits of this build

* The ML-dependent paths (embedding, re-ranking, NLI) were written and type-checked but **their end-to-end tests were not run** in the final build (the machine had 2 GB of RAM). Earlier in the build the ingestion pipeline passed 11 end-to-end tests with the embedding model; after later refactors only the model-free subset was re-run.
* Thresholds that must come from labelled data (`NLI_THRESHOLD`, `RERANK_THRESHOLD`) are flagged placeholders.
* The corpus is 12 real documents, far below the design's minimum of 150 legal and 150 medical.
