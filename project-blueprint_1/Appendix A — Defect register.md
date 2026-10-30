---
title: Appendix A — Defect register
---

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