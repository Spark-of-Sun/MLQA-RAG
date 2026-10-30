clear
# Status of the MVP (read this before relying on any guarantee)

**Summary.** A working MVP of the platform: the data layer, security libraries, seven services, the frontend and the
infrastructure code are written and pass their **model-free** tests against **real** servers. It has **never run
end to end** with a real Auth0 tenant, real AWS, a real LLM, or the ML models, so the headline product behaviour
(a verified, cited answer) is **not yet demonstrated**. Treat every guarantee as a design claim until the gate that proves
it passes (see `agent_work/docs/TEST-REPORT.md` in the work-log archive).

## Verified (measured, repeatable: `make test`, `make lint`)

| Area | Evidence |
| --- | --- |
| Python tests that need no model or cloud | **446 passed** (stage-10 gate), 10 more Kubernetes tests (stage 11), 0 failed |
| Frontend | 34 Vitest tests; `tsc` strict and ESLint (0 warnings) clean; `next build` succeeds |
| Lint, types, boundaries | ruff clean (164 files), pyright 0 errors, 6 import contracts kept |
| Row-level security | equals a Python oracle on 260 random worlds; 7 deliberately injected policy bugs were all detected |
| Pooler safety | 10,000 interleaved transactions on a real PgBouncer, 0 context leaks |
| Audit | hash chain verifies; tampering detected at the exact event; writers cannot decrypt; shredding a month keeps the chain valid |
| Keys | envelope encryption, per-document shredding and organization-key destruction on real OpenBao |
| Tokens | Auth0-style token abuse cases rejected (locally signed, real JWKS endpoint); context tokens single-audience, 60 s, replay-safe |
| Revocation | a suspension blocks the user at the Gateway in under 2 s (real pub/sub) |
| Contracts | the authorization matrix, OpenAPI documents and implementation agree in both directions |
| Infrastructure code | `tofu validate` passes for AWS (6.71), Cloudflare (5.28), Auth0 (1.59); Kubernetes manifests pass 10 security-property tests |

## NOT verified (do not assume these work)

* **No real Auth0.** Sign-up, passkeys, MFA, token claims, and the method names the post-login Action sees (gate G2.7) are untested.
  The Action's strength logic is a best reading of Auth0's behaviour and **must be pinned against your tenant**.
* **No ML model ran in the final build** (2 GB machine). Embedding, re-ranking and NLI paths, the **full gated release**
  (generation -> validator -> verified sentences) and the 23 `live_models` tests are untested here. The 11 ingestion
  end-to-end tests passed earlier in the build and were **not re-run after later refactors**.
* **No real AWS KMS.** The adapter and the per-key KeyGuard policy are unit-tested and written to AWS's documented API
  but have never called AWS. Nothing was applied: `tofu plan/apply`, `kubectl`, `docker compose up` and the image builds were never run.
* **The frontend has never run in a browser** against a real backend: no Playwright, no accessibility run, no CSP violation check.
* **Thresholds are uncalibrated placeholders** (`NLI_THRESHOLD`, `RERANK_THRESHOLD`). Answer quality and the "supported"
  precision floor of 0.99 are unmeasured. The corpus is 12 documents (the design wants 150 + 150).

## Not built

Governance requests (successor transfer, wall lift, unseal, destroy, owner recovery, co-owner); the operator plane (`ops`)
and JIT access; the KeyGuard auto-cancel responder; break-glass and emergency-access **APIs** (their database rules exist and are
tested); exports; the held-documents queue; OCR (an engine and the review screen); the reconciler and audit-anchor jobs; quotas;
VPC / EKS / RDS / Valkey / Qdrant hosting code; Playwright, load, chaos and isolation-at-scale suites; the penetration test.
Deferred routes answer 404 (`contracts/features.toml`).

## Safe defaults that protect you while the above is open

* An unverified sentence cannot be released: no verdict, no valid signature, or no committed audit record means no output.
* A page without a text layer is quarantined and never embedded.
* Cache is off unless `ANSWER_CACHE=on`; medical organizations must opt in.
* Every service refuses to start with missing or placeholder settings, and a production KMS provider refuses to start without the KeyGuard roles.
* A disabled feature is a 404 for everyone.
