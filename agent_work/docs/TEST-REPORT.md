# Test report (final build)

Everything here was measured by running the thing, on a sandbox with **2 GB of RAM and no Docker**. Real servers
were started from downloaded binaries: PostgreSQL 18.6, PgBouncer 1.26.1 (built from source), Valkey 9.1.3 (built from
source), Qdrant 1.20.0, OpenBao 2.7.2, SeaweedFS 4.51. Nothing was mocked (see ADR 0007).

## What was run, and the result

| Lane | Command | Result |
| --- | --- | --- |
| Python, model-free, no cloud | `pytest -m "not live_models and not live_aws"` (gate for stage 10) | **446 passed**, 0 failed, 0 skipped (2 min 22 s). 10 more (Kubernetes manifests) belong to stage 11 and passed in their own run |
| Lint | `ruff format --check`, `ruff check` | clean across services, libs, tests, corpus, tools, infra (164 files) |
| Types | `pyright` (strict on `libs/`) | 0 errors, 0 warnings |
| Import boundaries | `lint-imports` | 6 contracts kept, 0 broken |
| Frontend unit | `pnpm test` (Vitest) | **34 passed** |
| Frontend types / lint | `pnpm typecheck`, `pnpm lint --max-warnings 0` | clean |
| Frontend build | `pnpm build` (Next.js 16.4.3, Turbopack) | succeeds; all app routes dynamic; `proxy.ts` recognised |
| Infrastructure | `tofu fmt -check`, `tofu validate` (OpenTofu 1.13.2) | AWS (provider 6.71), Cloudflare (5.28), Auth0 (1.59): all valid |
| Config / CI files | YAML parse | compose (3 files), k8s (41 documents), 5 GitHub workflows: all parse |

**Package proof.** The delivered zip was extracted into a clean directory, installed with `uv sync --frozen`, the corpus restored with
`make load-corpus` (12 documents, every SHA-256 matching the manifest), and the whole model-free suite run from there:
**456 passed, 0 failed**, 24 deselected (23 `live_models`, 1 `live_aws`). The frontend installed from `pnpm-lock.yaml` and passed `tsc` and 34 Vitest tests.

Stage gate attestation (kept in `gate-stage-10-attestation.json`; unsigned): `gates/stage-10.json` (unsigned; cosign signing is a CI step). The first two gate runs FAILED
honestly on lint findings that the unit tests did not show; both were fixed and re-run.

## Gate checks that were met (model-free half)

G0.5 import boundaries (with a failing control) . G0.6 secrets hygiene (`.env` ignored, `.env.example` tracked) .
G0.10 matrix and flags validate . G0.11 no mocks (ruff bans them) . G1.1 migrations apply, roll back and re-apply identically
. G1.2 role and table audit (non-owner, no BYPASSRLS, FORCE RLS everywhere, no PUBLIC grants) . G1.3 fail closed on a reused
pooled connection . G1.4 policies equal the oracle (260 random worlds; 7 injected bugs all detected) . G1.5 Super Admin
boundary . G1.6 composite foreign keys (every one) . G1.7 pooler safety (10,000 interleaved transactions, 0 leaks) . G1.8
audit chain and tamper detection . G1.9 state machines (every ordered pair) . G1.10 envelope encryption . G1.11 shredding
(OpenBao half) . G2.5 code security (uniform rejection, rate limits, constant-time work) . G2.8 lifecycle cascades . G3.1
token abuse (locally signed tokens, real JWKS endpoint) . G3.3 context tokens (all service pairs) . G3.4 revocation under 2 s
. G3.5 signer certificates (2000 mints = 1 trust-root call, p99 < 5 ms) . G3.6 authorization matrix and OpenAPI drift .
G3.8 step-up challenge . G3.9 limits and idempotency . G4.2 chunk fidelity (100% on 12 real documents) . G5.1 vector
wrapper and read-only key . G5.4 vector filter contains RLS . G6.1 to G6.5 budget, trimming, prompt, cache .
G7.1 to G7.2 validator checks and segmentation . G7.4 determinism . G7.5 critical tokens . G7.6 integrity and signatures .
G9.2 audit sealing . G9.2 crypto-shred leaves the chain verifiable . G8.4 (helper half) SSE sliced at every byte boundary.

## NOT run: test these later (exact commands)

| What | Why it did not run | How to run it |
| --- | --- | --- |
| `live_models`: 23 tests (11 ingestion e2e, 11 retrieval e2e, 1 NLI validator) | **Your instruction: no ML models on a 2 GB machine.** The 11 ingestion e2e tests *did* pass earlier in the build, before later refactors; they were not re-run after | `make test-models` on a machine with at least 8 GB |
| `live_aws`: 1 test (schedule / cancel / enable a real key, encryption context) | no AWS credentials | `make test-aws` with credentials; it creates and schedules deletion of a `drill`-tagged key |
| Live Auth0: sign-up, passkeys, token claims, method names the Action sees (G0.7, G2.1-G2.4, G2.6, G2.7, G3.1 with real tokens) | no Auth0 tenant | `pytest -m live_auth0` (the Playwright harness is **not written**) |
| Full gated release end to end (generation -> validator -> verified sentences) (G7.7, G7.8, G7.9 for the passing path) | needs a real LLM key and the NLI model | after `make test-models` passes, run a live query lane |
| Entailment calibration (G7.3), retrieval quality (G5.3), refusal accuracy (G6.7) | need human-labelled data (R10) and models | label >= 300 pairs per domain, then set `NLI_THRESHOLD` / `RERANK_THRESHOLD` |
| Real PgBouncer with the shipped `pgbouncer.ini` (SCRAM + `auth_query`) | the sandbox PgBouncer used `trust` auth | `docker compose up pgbouncer` and connect as a service role with its password |
| `docker compose up` for the whole stack; image builds | no Docker in the sandbox | `make up`; first run will likely need small fixes |
| Frontend in a browser: route matrix with real tokens (G8.1), onboarding e2e (G8.2), CSP violations (G8.6), axe accessibility (G8.7), citation panel (G8.9), responsiveness (G8.10) | no browser, no Auth0 | write the Playwright suite (not written) |
| `tofu plan` / `apply` for AWS, Cloudflare, Auth0; Kubernetes `kubectl apply` | no credentials, no cluster | see `docs/deployment-onekami.md` |
| Load (G10.4), chaos (G10.5), isolation at scale (G10.2), DR drill (G9.10), destruction drill (G9.6), penetration test (G11.2), counsel review (G11.4) | out of scope for an MVP build | stages 10 and 11 of the plan |
| `gitleaks` scan | binary not installed in the sandbox | runs in CI and as a pre-commit hook |
