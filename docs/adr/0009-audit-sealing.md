# ADR 0009: Sealed audit payloads and a separate audit service

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 13.1 to 13.3, 13.5, 12.1, 4.2; decision D31; defects DEF-16, DEF-27; gates G1.8,
  G7.9, G9.1, G9.2

## Context

Audit records hold the most sensitive text in the system: questions, retrieved chunk references, answers and
verdicts. Every service writes audit events. In v2.1 payloads were encrypted with one symmetric key that every
writer needed, so every service could read every audit payload (DEF-27). The audit trail must also be
tamper-evident, survive retention (old partitions removed) and survive the shredding of a month's key, and the
Super Admin and operators must be able to review events about admins without reading content.

## Decision

- Two records per action (13.1): `audit_event` metadata (IDs, actor, action, target IDs, outcome, request ID,
  `prev_hash`, `hash`) and `audit_payload` content.
- D31 sealing (13.2): payloads are sealed with HPKE (RFC 9180) to the public key of an X25519 key pair per
  workspace per calendar month (ADR 0005). Writers hold only the public key: they can encrypt, not decrypt.
- A separate `audit` service (port 8007) is the only holder of a role that may unwrap the month's private key
  through KMS. It serves reads, search, export, chain verification and hourly anchoring.
- Writers use the `SECURITY DEFINER` function `audit_append` only; no service role holds INSERT, UPDATE or
  DELETE on audit tables, and a trigger rejects UPDATE and DELETE.
- Chains (13.3): one hash chain per workspace and one control-plane chain per organization, each computed by
  `audit_append` under a per-chain transaction-level advisory lock (safe under transaction pooling), with
  `hash = H(prev_hash + canonical event)`. The hash covers the payload ciphertext, so shredding a month's key
  leaves the chain verifiable.
- Hourly Merkle root over all chain heads, written to an Object Lock bucket in compliance mode.
- Retention: before a monthly partition is detached, a checkpoint record carrying the last hash is written
  and anchored; the verifier accepts a checkpoint as a chain start (DEF-16).
- Viewers (13.5): Super Admin sees org-level and admin-level events, never payloads; operators see
  infrastructure events only.

## Alternatives considered

- Symmetric payload key shared by writers: rejected (DEF-27).
- One chain per organization: rejected for production; it serializes every audit write of the organization.
  Kept only in the MVP.
- External logging service as the audit store: rejected; writes must commit in the same database transaction as
  the action they record (write-ahead release, ADR 0006).
- Audit reads served by each service: rejected; every service would need decrypt rights.

## Consequences

- Positive: a compromised writer cannot read past payloads; tamper evidence survives retention and shredding.
- Negative: an HPKE library with cross-implementation test vectors to maintain; a KMS decrypt on the read path;
  chain lock contention (budget 200 writes per second per workspace chain; shard by user hash if missed).
- Proven by G1.8 (valid chain, UPDATE and DELETE rejected, tamper detected, verification across a partition
  checkpoint), G7.9 (no release without a prior `segment.released` event), G9.1 (chain, checkpoints and anchors
  against the real Object Lock bucket) and G9.2 (writers cannot decrypt; destroying a month's key makes payloads
  unreadable while the chain verifies).

## Current state

Since task 3.8 (migration `0015_audit_chains`, DEV-18 closed) there is one SHA-256 chain per workspace and one
control chain per organization (`audit_chains`). `audit_append` (`db/policies/30_audit.sql`) is `SECURITY DEFINER`,
takes a transaction-level advisory lock per chain and locks the chain head. `audit_events` and `audit_payloads`
are partitioned by month (UTC). Payloads are sealed by `lmqa_audit.append(..., content=...)` with HPKE to the
workspace-month key and stored apart from the metadata; the chain covers their SHA-256. Triggers block UPDATE,
DELETE and TRUNCATE on every audit table. `audit_detach_month` writes anchored `partition_detach` checkpoints
before it detaches a month, and `audit_verify` starts each chain at its checkpoint. The MVP per-organization chain
is archived read-only as `audit_events_mvp` (`audit_verify_mvp`), and each control chain starts from its last hash
(`legacy_close` checkpoint).

Gaps: no call site passes content yet, so no payload is sealed in practice; anchoring and the Object Lock bucket
are coded but not run locally; the `audit` package still runs inside the gateway process (deviation 1).
