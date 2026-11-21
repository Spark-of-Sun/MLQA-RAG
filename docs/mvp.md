# MVP scope against the blueprint

The goal of this build is a working, demonstrable product on one machine. It follows the blueprint's design and
repository layout (section 18) and keeps every safety rule that makes the product what it is; it defers the
infrastructure and governance that matter at production scale. Everything deferred is listed below so it can be
added stage by stage without rework.

## Built, as designed

| Blueprint | In this MVP |
| --- | --- |
| 1.2, 5.1 Organization → workspace → member | One membership per person; Super Admin, Admin, Member (tenant) roles |
| 5.3 Super Admin boundary | No route (authz matrix → 404), no service path and no RLS policy on content |
| 5.4 Access decision | RLS on documents, chunks, queries, ledger: inactive → deny; own → allow; shared with workspace → allow; else deny. Admins cannot read members' private documents |
| 7.2–7.4 Onboarding paths A, B, C | Create organization; join as admin with the Organization Code (Super Admin approves; workspace `pending` → `active`); join as member with the Admin Code (admin approves); preview without consuming a use |
| 7.6 Codes | 64 / 32 characters, Crockford Base32, 8-character lookup ID, Luhn mod-32 check character (also checked in the browser), HMAC-SHA-256 with a versioned pepper, constant-time compare, shown once, rotation revokes, expiry and max uses, one identical error, per-user and per-IP failure limits, invite links in the URL fragment |
| 6 State machines | `contracts/state-machines.yaml` drives approve / reject / suspend / reactivate; illegal pairs answer 409; suspending an admin freezes the workspace |
| 8 Auth0 | Auth0 Universal Login through the Next.js SDK; RS256 access tokens checked for issuer, audience, expiry; role and status always from PostgreSQL |
| 9.4 Retrieval ledger | Aliases S1…Sn, chunk hashes, ranks and scores per answer |
| 10.3 Fail closed | No context → zero rows; transaction-local context, safe on pooled connections; runtime role NOBYPASSRLS |
| 11.1 Ingestion | PDF text layer, DOCX, HTML, XML (JATS, SPL drug labels, eCFR), TXT; magic-byte checks; safe XML parsing; structure-aware chunks with a preamble; `fallback` shown when no structure; all-or-nothing indexing |
| 11.3 Retrieval | Hybrid dense + full-text with reciprocal rank fusion, under RLS; whole chunks within a hard token budget |
| 11.5 Prompt protocol | Versioned files in `prompts/`, request-local aliases, untrusted-content rule, canonical refusal, SHA-256 recorded per answer |
| 11.6 Validator and gated release | V1–V5, V7, V8 deterministic, plus quote matching and lexical support; citation list built from validated sentences only; V3 re-checked against the database at release; query, ledger and audit event committed in one transaction before anything is returned; removed sentences shown as a visible marker |
| 13 Audit | Append-only, hash-chained per organization; UPDATE/DELETE/TRUNCATE blocked by trigger; verification detects tampering; views scoped by role |
| 17 Frontend | Next.js 16 `proxy.ts`, Auth0 SDK, BFF that alone holds tokens, nonce-based strict CSP, route groups per role with 404 for forbidden routes, chat with citation side panel and highlighted spans, library, manage admins, manage members, audit, onboarding |

## Deliberate deviations (to revisit at the named stage)

| # | Blueprint | MVP | Why / when |
| --- | --- | --- | --- |
| 1 | Eight deployable services | Eight service packages in one gateway process | One machine; the package boundaries (blueprint 18 import rules) are kept, so splitting is deployment work (Stage 3) |
| 2 | Qdrant behind `lmqa_vectorstore` | pgvector in PostgreSQL behind the same library | The blueprint's own fallback (10.5, ADR 0004): vectors fall under the same RLS. Revisit at Stage 10 load tests |
| 3 | Self-hosted embedding, re-ranker and NLI models | Gemini embeddings (768 d); no re-ranker | 6.8 GB machine. Note: document text is sent to Google. Needs a no-retention / BAA agreement before real data (blueprint 11.8) |
| 4 | V6 pinned NLI model | A strict Gemini entailment pass that can only remove sentences | Not deterministic like a pinned model; it never approves what the deterministic checks rejected, and fails closed. Calibrate with labelled data (G7.3) |
| 5 | Sentence-by-sentence SSE streaming | Whole answer validated, then returned (the blueprint's `buffered` mode) | Simpler and equally safe; streaming is a latency feature (Stage 7) |
| 6 | AWS KMS, envelope encryption, KeyGuard, crypto-shredding | Not built; originals on local disk, chunk text in PostgreSQL | Stage 1 key work and Stage 9 destruction ritual |
| 7 | Auth0 Organizations, passkeys, step-up, separate onboarding audience | One API audience; roles in PostgreSQL only | Stage 2; the gateway already ignores role claims |
| 8 | Server-side session store, opaque session ID | SDK's encrypted session cookie; access-token endpoint disabled | Stage 8 with Valkey |
| 9 | Context tokens, signer certificates, revocation pub/sub | In-process calls; suspension applies on the next request | Stage 3, when services split |
| 10 | Matters, confidentiality tiers, ethical walls, emergency access, break-glass | Workspace-shared or private documents only | Stage 5 policy rules |
| 11 | Governance requests, co-owner, successor transfer, operator plane | Not built | Stage 9 |
| 12 | ClamAV, OCR, object store, PgBouncer, Valkey, observability | Not built; scanned PDF pages are reported, never embedded | Stages 0, 4 |
| 13 | Gate suites, Playwright, load and chaos tests | `make demo` (50 checks) and `make demo-web` (21 checks) | Per your instruction for this phase |
| 14 | Separate idle limits per role | 30 min idle / 8 h absolute for everyone | One SDK setting |

## Model availability

`LLM_MODEL` is tried first; on HTTP 429/503 or a timeout the next model in `LLM_FALLBACK_MODELS` is used and the
busy model is skipped for two minutes. The model that produced each answer is shown in its verification details
and recorded in the audit event.
