---
title: Appendix C — Configuration catalog (names only) and policy minimums
---

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