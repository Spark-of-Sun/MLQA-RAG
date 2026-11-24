# ADR 0008: Context tokens signed by KMS-certified ephemeral keys

- Status: Accepted, MVP deviation in force (date 2026-11-22)
- Blueprint: sections 9.1 to 9.3, 4.3, 12.1, 22; decision D29; defects DEF-10, DEF-26, DEF-49;
  gates G3.3, G3.5, G4.7

## Context

Once services are split (ADR 0001), each service must know on whose behalf it is called, and must re-check
permissions itself. Forwarding the user's Auth0 token would give every service a credential that works
everywhere. A shared internal key would let any compromised container impersonate any user and service
(DEF-10). Signing every context token with a KMS API call puts KMS latency on every request and hits KMS
signing quotas under load (DEF-26).

## Decision

- After resolving the principal, the Gateway mints a context token for one target service: ES256 JWT, valid
  60 seconds at the start of the call, single audience, claims `sub`, `org_id`, `workspace_id`, `role`,
  `auth_strength`, `scope_hash`, `scope_version`, `pv`, `request_id`, `jti`. The Auth0 token is never forwarded.
- `scope_hash` and `scope_version` come from the `principal_v` view, maintained by triggers when grants, walls,
  exceptions, sessions or workspace flags change; the Gateway never reads the underlying tables (DEF-49).
- Services verify signature, audience, expiry and issuer against the internal trust bundle, build their
  database context from these claims only, and reject a reused `jti` on state-changing calls.
- D29 signing: each Gateway instance generates an in-memory ES256 key pair every hour. A KMS asymmetric trust
  root (ECC P-256, sign and verify only, never exported, rotated every 90 days with overlap) signs a signer
  certificate binding that public key to the instance's workload identity for at most one hour. Tokens
  reference the certificate in their header; services cache certificates and consult a deny-list in Valkey.
- Long-running work compares `pv` at checkpoints and aborts on mismatch. The Validator signs verdicts with an
  equivalent certified key (ADR 0006). Background jobs carry a signed envelope (9.3).
- Each service also has its own credential: per-service secrets locally, mTLS with workload identity in production.

## Alternatives considered

- Forward the Auth0 access token: rejected; a token valid at every service, and audience checks lose meaning.
- Shared HMAC key for all services: rejected; any holder can mint any identity (DEF-10).
- KMS `Sign` per token: rejected; latency and quota bottleneck (DEF-26).
- Long-lived per-instance signing keys on disk: rejected; a stolen key stays useful and is hard to revoke.

## Consequences

- Positive: about one KMS call per instance per hour; a stolen signer key dies within the hour; revoking a pod
  is one deny-list entry.
- Negative: certificate distribution, caching and deny-list checks in every service; clock skew matters.
- Proven by G3.3 (single audience, 60 s expiry, `jti` reuse rejected, `pv` mismatch aborts, every service pair
  rejects a token for another audience), G3.5 (about one KMS call per instance per hour, minting p99 at most
  5 ms, deny-list revokes within 2 s) and G4.7 (tampered or expired job envelope rejected).

## Current state

Not built. The MVP calls services in-process inside the gateway, so no context tokens, signer certificates or
revocation pub/sub exist; suspension applies on the next request (deviation 9 in [docs/mvp.md](../mvp.md)).
The database context is set per transaction from the principal the Gateway resolved, and the runtime role is
`NOBYPASSRLS`, so RLS still decides visibility. There is no KMS (deviation 6), so no trust root exists yet.

Stage 3 closes the gap, together with the service split (ADR 0001); the KMS trust root depends on Stage 1 key work.
