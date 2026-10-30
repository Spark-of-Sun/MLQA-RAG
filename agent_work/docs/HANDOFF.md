# Handoff: what to do next, in order

## 0. What you have

* `legal-medical-qa.zip`: the project (`.env` holds placeholders only).
* `agent_work.zip`: the strict work log (`logs/worklog.md`, plus a machine-readable `worklog.jsonl`), these documents, and
  the helper scripts I used while building (`tools/`).
* Read `docs/STATUS.md` in the project first. It says plainly what was and was not verified.

## 1. First hour (on your own machine)

1. Install Docker, Python 3.14 (via `uv`), Node 24, pnpm. `make sync`.
2. `make env FORCE=1` (random local secrets), `make infra-test`, `make migrate`, `make load-corpus` (the real public documents are fetched, not shipped), `make test`. You should see the same
   446 model-free tests pass. If something differs, that is real information: tell me.
3. `make doctor` shows which third-party values are still placeholders.

## 2. Things only you can provide (I cannot and did not invent any of these)

| Needed | For |
| --- | --- |
| Auth0 tenant (plan with Organizations + MFA; Enterprise + BAA add-on before any PHI) and a management M2M app | `infra/auth0`, login |
| AWS account (and a separate vault account for escrow in production), IAM roles `keyguard-destroyer` and `key-admin` | `infra/aws`, KMS |
| Cloudflare account with the `onekami.site` zone and a zone-scoped API token | `infra/cloudflare` |
| An LLM provider key with no-retention terms (and a BAA for medical) | generation |
| SMTP and an on-call webhook | notifications, alerts |

## 3. The tests I could not run: do these before trusting any answer

On a machine with at least 8 GB: `make test-models` (23 tests: ingestion, retrieval and validator end to end with real models), then `make test-aws` (needs credentials).
Then calibrate: label at least 300 sentence-versus-passage pairs per domain with a qualified attorney or clinician,
and set `NLI_THRESHOLD` (precision of "supported" at least 0.99) and `RERANK_THRESHOLD`. Details: `TEST-REPORT.md`.

## 4. Build next (highest value first)

1. **Live Auth0 harness** (`tools/auth_harness`, Playwright with a virtual WebAuthn authenticator) and pin the method
   names the post-login Action sees (G2.7). Until then the privileged-role strength check is unproven.
2. **Playwright + axe suite** for the frontend (route matrix, onboarding, CSP, accessibility, citation panel).
3. **Governance requests** (two-person flows), then `ops` (operator plane), then successor transfer and owner recovery.
4. **KeyGuard auto-cancel responder** Lambda and the tombstone-replay tool for restores.
5. **Queue spike G0.13** (Procrastinate through PgBouncer) and move ingestion off the in-process task.
6. **OCR**: install Tesseract, add an engine to the parser and the review screen.
7. **Reconciler + audit anchor jobs**, then load, chaos and isolation-at-scale suites (stage 10).
8. Production infrastructure: VPC, EKS, managed PostgreSQL 18 + PgBouncer, Valkey, Qdrant (stage 11), then the external
   penetration test, counsel review and vendor agreements.

## 5. Questions for you

* Is my MVP scope right (`MVP-SCOPE.md`)? The document's companion "MVP Prototype Report and Process" was not supplied.
* Medical or legal first? It decides which compliance work (BAA, retention, emergency access) comes before real data.
* Do you want a single staging host first (Path A in `docs/deployment-onekami.md`) or straight to EKS?
