# ADR 0007: Real data and no mocks

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 19.1, 19.2, 19.6, Appendix B; decisions D27, D28; defect DEF-10; gates G0.8, G0.9,
  G0.11, G2.10, G11.1

## Context

The guarantees this system makes (RLS isolation, key shredding, Auth0 suspension, citation validation) depend
on how real systems behave: PgBouncer reusing connections, KMS deletion windows, Auth0 method names, LLM
output that breaks the tag grammar. Mocks and generated text encode the author's assumptions about those
systems, so tests pass while the product fails. The earlier plans had a mock IdP, a file-backed KMS, a
mockable LLM client and a demo seed, which could not test key deletion or the Auth0 flows (DEF-10).

Real data has its own limits: customer documents and PHI must never leave production, and credentialed
clinical datasets restrict sending text to third-party APIs.

## Decision

- D28: no mocks or fake data anywhere. Rules R1 to R10 (19.1), including:
  - R1 real documents only, loaded from `corpus/manifest.toml` through `lmqa_testing`;
  - R2 real systems only: PostgreSQL, Qdrant, Valkey, object store, KMS, Auth0, LLM, embedding, re-ranking and
    entailment models, SMTP and IMAP. `ruff` TID251 bans `unittest.mock`, `pytest_mock`, `respx`, `responses`,
    `faker`, `factory` and `freezegun`;
  - R5 real accounts and flows: data enters through the product's onboarding and upload APIs, never SQL inserts;
  - R7 time acceleration only through configuration, with a lint against production minimums;
  - R9 recorded LLM responses only in the fast pull-request lane and under 14 days old; every gate runs live.
- R6: labeled negative controls (EICAR, planted secrets, malformed JWTs, public adversarial prompts and XSS
  strings, injected faults) are instruments, listed in `tests/controls.md` and marked `@pytest.mark.control`.
- D27: a public real corpus with recorded URL, licence, retrieval date and SHA-256 per item (R3); credentialed
  medical data such as MIMIC-IV-Note only in an opt-in lane with self-hosted models, never in shared CI (R4).
- R10: evaluation labels come from published datasets or qualified domain reviewers, never from the model
  under test.
- `make doctor` verifies every real dependency before any test runs.

## Alternatives considered

- Mocks for speed in unit and integration tests: rejected; the failures that matter here live in the real
  systems' behavior. Pure functions are covered by the `unit` marker with no I/O instead.
- Synthetic documents for scale: rejected; scale comes from replicating real documents into many workspaces (R8).
- In-memory substitutes (SQLite, fake KMS): rejected; they lack RLS, pooling and deletion-window semantics.

## Consequences

- Positive: a passing gate is evidence about the real stack, including vendor behavior changes.
- Negative: slower and costlier test runs; live LLM spend caps; Auth0 and KMS rate limits shape the fixtures;
  CI needs real accounts and project-owned mailboxes.
- Negative: public clinical notes with SOAP structure are scarce, so that coverage waits for the credentialed
  lane or a pilot under a BAA (Stage 11).
- Proven by G0.8 (manifest hashes, licences, minimum counts such as 150 legal and 150 medical documents),
  G0.9 (real dependency doctor), G0.11 (a `unittest.mock` import fails `ruff`; `faker` absent from the lockfile)
  and the gatekeeper's live-lane count (R9).

## Current state

The `ruff` banned-API list in `pyproject.toml` matches 19.3 and the control C-MOCK in `tests/controls.md`
proves it; the lockfile contains none of the banned packages. `corpus/manifest.toml` holds 12 items (6 legal,
6 medical), below the G0.8 minimums. Tests use real PostgreSQL, PgBouncer, Valkey, Qdrant, SeaweedFS and
OpenBao (`tests/integration/`). The answer and embedding providers are real Gemini or other providers, which
means document text leaves the machine (deviation 3 in [docs/mvp.md](../mvp.md)); only the public corpus may
be used until a no-retention or BAA agreement exists.

Gaps: the gate suites are replaced for now by `make demo` and `make demo-web` (deviation 13). The demos and
`make eval` sign in with real Auth0 accounts through the auth harness (`tools/real_identity.py`); the local
RS256 signer and the settings overrides that pointed the gateway at it were removed (DEV-35). Stage 0 closes the corpus counts (G0.8); Stage 2 brings real Auth0 test identities (G0.7, G2).
