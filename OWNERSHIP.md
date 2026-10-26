# OWNERSHIP.md

**Owner: coordinator only.** No developer edits this file. A formal ownership change is a coordinator commit to this file with the trailer `Ownership-Change: <from> -> <to> <path>` and a note in `status/SHARED_STATUS.md`.

Plan of record: *MVP Prototype Report and Process v1.0* (release M1) on top of *Master System Design v3.1*. The earlier Skeleton, Muscles and Skin phase reports are superseded.

Rules: every file or directory has exactly one owner. A trailing `/` means everything below that path. `name_*` means files in that directory whose names start with `name_`. A path not listed here is **unowned**: nobody creates or modifies it until the coordinator assigns it. An owner may create the directory chain that leads to a path they own. Everyone may **read** everything. Everyone may write `status/SHARED_STATUS.md` under the rules in their instructions, and nothing else outside their own paths.

Status: **PROPOSED DEFAULTS.** The coordinator confirms or changes the decisions at the bottom before P0 starts.

## Maya Okafor, Platform and Data Engineer

Also acts as: tech lead and release manager hats (ADRs, debt register, gatekeeper, M1 tag).

- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `.gitignore`
- `.gitattributes`
- `.editorconfig`
- `.gitleaks.toml`
- `.pre-commit-config.yaml`
- `.importlinter`
- `Makefile`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `.env.example`
- `compose.yaml`
- `compose.override.yaml`
- `compose.test.yaml`
- `stages.toml`
- `STAGE`
- `gates/`
- `.github/`
- `infra/compose/`
- `db/`
- `libs/lmqa_models/`
- `libs/lmqa_db/`
- `libs/lmqa_audit/`
- `libs/lmqa_logging/`
- `libs/lmqa_telemetry/`
- `services/audit/`
- `tools/gatekeeper/`
- `tools/doctor/`
- `tools/state_machine_gen/`
- `tools/ownership_check/`
- `tools/queue_spike/`
- `tools/versions_report/`
- `docs/architecture.md`
- `docs/versions.md`
- `docs/diagrams/`
- `docs/adr/`
- `docs/runbooks/`
- `docs/debt-register.md`
- `contracts/state-machines.yaml`
- `contracts/features.toml`
- `contracts/schemas/`
- `contracts/openapi/audit.yaml`
- `contracts/events/audit_*`  (files starting with this prefix)
- `logs/maya_progress.md`

## Daniel Reyes, Identity, Gateway and Key Security Engineer

Also acts as: security lead hat (reviews high-risk paths with REVIEW comments).

- `services/gateway/`
- `services/identity/`
- `services/ops/`
- `libs/lmqa_auth/`
- `libs/lmqa_keys/`
- `libs/lmqa_security/`
- `infra/auth0/`
- `infra/aws/`
- `infra/keyguard/`
- `tools/auth_harness/`
- `contracts/openapi/gateway.yaml`
- `contracts/openapi/identity.yaml`
- `contracts/openapi/ops.yaml`
- `contracts/authz-matrix.yaml`
- `contracts/claims/`
- `contracts/events/token_*`  (files starting with this prefix)
- `logs/daniel_progress.md`

## Priya Nair, Ingestion and Corpus Engineer

Also acts as: data steward hat (corpus manifest, licences, upload allow-list).

- `services/ingestion/`
- `libs/lmqa_objectstore/`
- `corpus/`
- `tools/load_corpus/`
- `contracts/openapi/ingestion.yaml`
- `contracts/events/ingestion_*`  (files starting with this prefix)
- `logs/priya_progress.md`

## Lucas Weber, Retrieval and Validation Engineer

Also acts as: evaluation and labels coordinator hat (question sets, calibration, floors).

- `services/retrieval/`
- `services/generation/`
- `services/citation_validator/`
- `libs/lmqa_vectorstore/`
- `libs/lmqa_release/`
- `prompts/`
- `eval/`
- `contracts/openapi/retrieval.yaml`
- `contracts/openapi/generation.yaml`
- `contracts/openapi/citation-validator.yaml`
- `contracts/events/retrieval_*`  (files starting with this prefix)
- `contracts/events/validation_*`  (files starting with this prefix)
- `logs/lucas_progress.md`

## Hana Sato, Frontend and Verification Engineer

Also acts as: QA and automation lead hat (acceptance run, run report).

- `frontend/`
- `libs/lmqa_testing/`
- `tests/`
- `tools/leakscan/`
- `tools/mvp_report/`
- `docs/acceptance/`
- `logs/hana_progress.md`

## Coordinator-owned (read-only for all developers)

- `OWNERSHIP.md`
- `CODEOWNERS`
- `docs/design/`
- `docs/compliance/`

## Shared write surface

- `status/SHARED_STATUS.md`: each developer edits only their own `### <Name>: Latest update` block; anyone may append comments under `#### Comments on <Name>'s latest update`.

## Roles from the MVP report (section 11.1)

| MVP report role (section 11.1) | Who | Note |
| --- | --- | --- |
| Product owner | The coordinator (human) | Scope, acceptance sign-off, flag decisions |
| Tech lead | Maya | Architecture conformance, ADRs, gatekeeper ownership |
| Security lead | Daniel | Reviews `db/policies/`, key controls, authorization matrix, isolation suite results. A second reader other than the author is required for his own files |
| QA and automation lead | Hana | Acceptance run, Playwright and provenance tooling, run report |
| Data steward | Priya | Corpus manifest, licences, allow-list |
| Domain reviewers (an attorney and a clinician) | Named humans outside the projects | Question sets, unanswerable questions, 100 labeled pairs per domain, review of released answers. Lucas coordinates |
| Release manager | Maya | Runs the gatekeeper, signs attestations, cuts the M1 tag |

A role gives responsibility and a duty to answer questions. It never gives authority to edit another developer's files.

## Which developer answers for which phase (MVP section 7.2 and gate matrix 8.2)

| Phase | Primary owner | Also contributing |
| --- | --- | --- |
| P0 Foundation | Maya | Daniel (Auth0, AWS, harness), Priya (corpus), Lucas (models, eval sources), Hana (test library, frontend skeleton) |
| P1 Data layer and keys | Maya (schema, RLS, audit chain), Daniel (keys, KeyGuard) | Hana (oracle) |
| P2 Identity and gateway | Daniel | Maya (state-machine tests, support), Hana (e2e) |
| P3 Ingestion | Priya | Lucas (vector wrapper, embedding), Daniel (keys) |
| P4 Retrieval, generation, validation | Lucas | Daniel (Gateway wiring), Hana (isolation suite) |
| P5 Frontend, audit, alerts | Hana (frontend), Maya (audit service, three alerts), Daniel (two alerts) | Priya (OCR review API) |
| P6 Acceptance and run report | Hana | Everyone; Maya signs attestations and cuts the M1 tag |

## Coordinator decisions needed (proposed defaults in bold)

| ID | Decision | Proposed default | Alternative |
| --- | --- | --- | --- |
| CD-1 | Who is the coordinator, and how are ownership changes recorded? | **A named person; commit to this file with the `Ownership-Change` trailer** | A rotating role |
| CD-2 | Direct push to `beta`, with the gatekeeper and gates running on each push and `main` staying PR-only? The MVP report assumes PRs; the path rule `STAGE + 1` is applied to the pushed range | **Yes** (as requested) | PRs into `beta` |
| CD-3 | Split of the data and key layer: schema, RLS, audit to Maya; keys, KMS, KeyGuard, security library to Daniel | **As listed here** | Everything to Maya, or everything to Daniel |
| CD-4 | Layout additions beyond Master §18: new library `libs/lmqa_release` (Lucas), which the Gateway imports; embedding wrappers inside `libs/lmqa_vectorstore` (no new inference service, per C3). `import-linter` rules updated by Maya | **Accept** (record as an ADR addendum) | Release logic inside `services/gateway` written by Daniel |
| CD-5 | The policy oracle must insert scenario rows at database level, which conflicts with the no-seeding rule and MG2 | **Allowed only as labeled instruments listed in `tests/controls.md`, against a scratch database, with real corpus excerpts; approved by the coordinator and Daniel (security lead)** | Test the policies through the product APIs only (far fewer scenarios) |
| CD-6 | `stages.toml` stage assignment for parallel-stream paths (`corpus/`, `infra/auth0/`, `libs/lmqa_testing/`, `tools/mvp_report/`, `tools/auth_harness/`, `tools/leakscan/`) | **Assigned to the earliest stage that needs them (stage 0 or 2) by Maya** | Everything strictly by phase |
| CD-7 | `uv.lock` has one owner. Turnaround for relock requests | **At least once per working day** | Hourly during integration |
| CD-8 | How project knowledge stays in sync with `beta` | **Project GitHub sync of `beta` if the plan offers it, otherwise a daily export uploaded by the coordinator** | Developers upload files they depend on each session |
| CD-9 | `logs/` and `status/` are team-process directories allowed by the MG3 layout check | **Allowed** | Move them under `docs/team/` |
| CD-10 | Observability stack (OTel, Grafana, Loki, Tempo): not required by the MVP report | **Not built in M1; structured redacted logging stays** | Assign to Maya |
| CD-12 | Approve the M1a cut list in `SCOPE_CUTS_M1a.md` (commit it under `docs/design/`). The report's own M1 tag rules stay in force | **Approve** | Build full M1 directly |
| CD-13 | Object store is AWS S3 in all environments (no SeaweedFS); EC2 instance metadata blocked from containers (IMDSv2 hop limit 1) | **Approve** | Keep SeaweedFS and its probe |
| CD-11 | MVP report open decisions: MD1 host sizing (Maya proposes), MD2 LLM provider (Lucas), MD3 named attorney and clinician reviewers (coordinator, week 1), MD4 corpus mix (Priya), MD5 Auth0 plan (Daniel), MD6 two named operators (Daniel, by P1), MD7 extra testers (coordinator, by P5) | **As listed** | |

## Adjustments this ownership model makes to the documents

1. **One branch.** The MVP report assumes pull requests and a gatekeeper on PRs. With one shared `beta` branch, CI and the gatekeeper run after each push and a failing check is a `BLOCKER`. `main` stays PR-only (promoted from `beta` by Maya).
2. **Dockerfiles stay in service directories** (Master §18) and are owned by each service's owner, written from the template and base images that Maya publishes under `infra/compose/templates/`.
3. **Single-file contracts have one owner**: `contracts/state-machines.yaml`, `contracts/features.toml` and `contracts/schemas/` (Maya), `contracts/authz-matrix.yaml` (Daniel), `eval/floors.toml` (Lucas). Others request changes as dependencies. OpenAPI files are owned by the service owner. Event schemas in `contracts/events/` are owned by filename prefix (`audit_`, `token_`, `ingestion_`, `retrieval_`, `validation_`).
4. **Generated state-machine tests** live in `tools/state_machine_gen/generated_tests/` (Maya) and run in `make gate`; Hana's `tests/` does not copy them.
5. **Complete schema in P1 by Maya** (C2). Later additive changes go through Maya as dependencies.
6. **Team-process files** `logs/` and `status/` sit outside the product layout.
7. **Removed from the earlier instruction set** because the MVP report does not contain them: per-developer manifests, `FILES.toml`, the AI file checker and its calibration, the separate `inference` service, the split vector library, per-developer migration directories.
8. **Added** (from your ownership rules, not from the MVP report): `tools/ownership_check` (with a `--patch` mode) and the CI job `ownership / path-check` (Maya).
9. **Patch delivery.** Claude produces patches, not file edits. Developers apply them with `git apply` on `beta`. See `PATCH_WORKFLOW.md`.
