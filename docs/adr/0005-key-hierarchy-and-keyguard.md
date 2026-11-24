# ADR 0005: Key hierarchy and KeyGuard

- Status: Accepted, MVP deviation in force (date 2026-11-22)
- Blueprint: section 12 (12.1 to 12.10); principles 9 and 11; decision D23; defects DEF-03, DEF-04, DEF-10,
  DEF-56; gates G1.10, G1.11, G1.12, G9.6, G9.12

## Context

Customers need provable deletion: when a document, workspace or organization is deleted, its content must be
unreadable everywhere, including backups. The earlier design derived workspace and audit keys from one data
key with HKDF, so a sub-key could not be destroyed on its own (DEF-03). At the same time, a per-organization
key makes one accidental or malicious deletion permanent, and even scheduling deletion makes a key unusable.

## Decision

- Hierarchy (12.1): an organization CMK in KMS (multi-Region primary plus replica) wraps independent random
  keys: a versioned 256-bit workspace content key, an X25519 audit key pair per workspace per month, and an
  organization control key. The workspace key wraps one 256-bit document key per document and a daily cache key.
  The document key encrypts that document's chunk text and stored object.
- Column encryption with AES-256-GCM; associated data binds `org_id`, `workspace_id`, object ID and version, so
  copied ciphertext fails to decrypt. Equality lookups use HMAC blind indexes.
- Escrow: wrapped copies of workspace, control and audit keys under a per-organization escrow CMK in a separate
  vault account. Sealing removes the CMK-wrapped copy; unsealing needs two custodians (no separate seal key, DEF-56).
- KeyGuard guardrails (12.5): a service control policy and key policies deny `kms:ScheduleKeyDeletion`,
  `kms:DisableKey`, `kms:PutKeyPolicy` and `kms:DeleteImportedKeyMaterial` for every principal except
  `keyguard-destroyer` (assumed only by the KeyGuard workflow with two distinct approval IDs in session tags) and
  `key-admin` (MFA and a change ticket). Service roles get only `Encrypt`, `Decrypt`, `GenerateDataKey`,
  `ReEncrypt` with encryption-context conditions.
- Windows: always the 30-day maximum for non-drill keys, linted in CI. Destroying needs two people, passkey
  step-up and a window; restoring needs one person or the automated responder, which cancels any unapproved
  scheduled deletion within 60 seconds of the event.
- Organization destruction takes at least 60 days (30-day grace plus the provider window). A tombstone ledger
  outside the backup set is replayed on every restore (DEF-04); backups expire within 35 days.
- D23: AWS KMS is the reference; OpenBao Transit for tests that need immediate shredding. No file-backed fake (DEF-10).

## Alternatives considered

- HKDF-derived sub-keys: rejected; cannot be shredded independently (DEF-03).
- One platform-wide key: rejected; no per-customer erasure and a single point of total loss.
- Relying on SSE-KMS only: rejected; not identical across local stores and leaves plaintext in the store
  process (ADR 0010).
- Allowing short deletion windows for agility: rejected; scheduling is itself an availability attack.

## Consequences

- Positive: deletion is provable by key destruction at document, workspace and organization level.
- Positive: deleting a key by mistake is slow, loud and reversible within the window.
- Negative: KMS calls and quotas (budget: at most 5% of regional quota with a 15-minute workspace key cache);
  an escrow account, custodians and drills to operate.
- Proven by G1.10 (envelope round trip, wrong associated data and wrong workspace fail), G1.11 (shredding on
  OpenBao and AWS KMS schedule and cancel), G1.12 (KeyGuard denies, window lint, responder within 60 s), G9.6
  (destruction drill) and G9.12 (key alerts and escrow restore).

## Current state

Not built. The MVP has no KMS, envelope encryption, KeyGuard or crypto-shredding: originals are on local disk
and chunk text is in PostgreSQL in clear (deviation 6 in [docs/mvp.md](../mvp.md)). The only key work present
is Stage 0 infrastructure: OpenBao 2.7.2 runs in Compose and `test_openbao_transit_round_trip_and_destruction`
in `tests/integration/test_stage0_infra.py` proves a Transit round trip and destruction. Join codes already use
HMAC-SHA-256 with a versioned pepper.

Stage 1 closes the key hierarchy, envelope encryption and KeyGuard preventive controls (G1.10 to G1.12);
Stage 9 closes the destruction ritual, escrow drills and key alerts (G9.6, G9.12).
