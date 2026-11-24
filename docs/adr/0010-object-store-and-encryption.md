# ADR 0010: Object store and application-level encryption

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 12.3, 4.5, 4.8, 10.2, 10.8; decision D19; gates G0.4, G0.9, G4.1, G4.9, G4.11

## Context

Original uploads must be stored durably, with presigned uploads from the browser, checksums and versioning.
Production uses S3. Locally the obvious choice, MinIO community edition, entered maintenance mode in December
2025. S3-compatible local stores also differ from S3 on Object Lock and on SSE-KMS encryption context, so
relying on server-side encryption would make local and production behave differently (principle 8) and would
leave plaintext inside the store process.

## Decision

- Production: S3. Local and CI: SeaweedFS (D19), accepted only if it passes a capability probe (G0.4).
- Application-level envelope encryption (12.3), identical locally and in production:
  1. Uploads land in a quarantine prefix via presigned PUT (60 s or less, constrained to the workspace prefix,
     size, content type and a required SHA-256 checksum). Production adds SSE-KMS and a 24-hour lifecycle
     expiry; locally the quarantine is plaintext, acceptable because local data is public documents only (R4).
  2. After scanning and parsing, the worker streams the file through chunked AES-GCM (1 MiB segments,
     per-segment nonces, a final-segment marker so truncation is detected) under the document key (ADR 0005),
     writes it to the final prefix and deletes the quarantine object.
  3. Downloads are decrypted and streamed by `ingestion` through the Gateway. The browser never receives a URL
     to ciphertext; presigned URLs exist only for uploads to quarantine.
- Object keys `org_{id}/ws_{id}/doc_{id}/v{n}` are built server-side from database rows, never from client
  input. A prefix is naming, not a control.
- Only `ingestion` and its workers hold object-store credentials (4.7). Production adds SSE-KMS with the
  organization CMK beneath the application layer. Object Lock is exercised only on real S3 (audit anchors, ADR 0009).
- No deduplication across workspaces: the same file in two workspaces gets distinct keys and ciphertext (10.8).

## Alternatives considered

- MinIO community edition: rejected; maintenance mode since December 2025.
- SSE-KMS only, no application encryption: rejected; behavior differs between local stores and S3, and the
  store holds plaintext.
- Local filesystem in CI: rejected; no presigned URLs, versioning or checksum semantics (R2).
- Another S3-compatible local store: G0.4 allows selecting an alternate if SeaweedFS fails the probe. Not
  needed (below).

## Consequences

- Positive: deleting a document key makes its stored object unreadable everywhere (G4.11); behavior is
  identical in every environment.
- Negative: downloads pass through `ingestion` and the Gateway instead of going straight to the store; the
  streaming AES-GCM format is ours to maintain and test.
- Proven by G0.4 (capability probe), G0.9 (Object Lock write succeeds and delete is refused on real S3), G4.1
  (bad checksum rejected, URLs cannot write outside the prefix and expire within 60 s) and G4.9 (no
  cross-workspace deduplication).

## Current state

D19 is confirmed. SeaweedFS 4.54 (image `chrislusf/seaweedfs`, pinned by digest in `compose.yaml` and
[docs/versions.md](../versions.md)) passed the Stage 0 capability probe on 2026-11-22:

- bucket versioning;
- presigned PUT and GET;
- presigned expiry enforced (403 after expiry);
- multipart upload;
- `x-amz-checksum-sha256` accepted, and a wrong checksum rejected;
- per-identity bucket-scoped credentials: the ingestion identity cannot write outside bucket `lmqa-objects`.

No alternate store is needed. Probe code: `object_store_capabilities()` in
`libs/lmqa_testing/src/lmqa_testing/infra.py`; test `test_object_store_passes_the_capability_probe` in
`tests/integration/test_stage0_infra.py`.

The product does not use the store yet. `lmqa_objectstore` writes originals to the local filesystem under
`data/objects` with server-built keys, unencrypted (deviations 6 and 12 in [docs/mvp.md](../mvp.md)). Stage 1
adds the document keys and Stage 4 moves uploads to the quarantine flow above (G4.1, G4.11).
