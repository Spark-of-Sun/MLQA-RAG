# OWNERSHIP.md

**Owner: coordinator only.** No developer edits this file. A formal ownership change is a coordinator commit to this file with the trailer `Ownership-Change: <from> -> <to> <path>` and a note in `status/SHARED_STATUS.md`.

Plan of record: *MVP Prototype Report and Process v1.0* (release M1) on top of *Master System Design v3.1*.

Rules: every file or directory has exactly one owner. A trailing `/` means everything below that path. `name_*` means files in that directory whose names start with `name_`. A path not listed here is **unowned**: nobody creates or modifies it until the coordinator assigns it. An owner may create the directory chain that leads to a path they own. Everyone may **read** everything. Everyone may write `status/SHARED_STATUS.md` under the rules in their instructions, and nothing else outside their own paths.

Status: **RESTRUCTURED (Daniel Reyes + Ganpati).** The project has transitioned to Daniel Reyes (Security Lead) and Ganpati (Lead Developer & Release Engineer).

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

## Ganpati, Project Lead and Platform Engineer

Also acts as: tech lead, data steward, QA lead, and release manager (driving M1a MVP delivery across platform, ingestion, retrieval, validation, testing, and pipeline).

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
- `infra/k8s/`
- `db/`
- `libs/lmqa_models/`
- `libs/lmqa_db/`
- `libs/lmqa_audit/`
- `libs/lmqa_logging/`
- `libs/lmqa_telemetry/`
- `libs/lmqa_objectstore/`
- `libs/lmqa_vectorstore/`
- `libs/lmqa_release/`
- `libs/lmqa_testing/`
- `services/audit/`
- `services/ingestion/`
- `services/retrieval/`
- `services/generation/`
- `services/citation_validator/`
- `corpus/`
- `frontend/`
- `prompts/`
- `eval/`
- `tests/`
- `tools/gatekeeper/`
- `tools/doctor/`
- `tools/load_corpus/`
- `tools/leakscan/`
- `tools/mvp_report/`
- `tools/state_machine_gen/`
- `tools/ownership_check/`
- `tools/queue_spike/`
- `tools/versions_report/`
- `docs/architecture.md`
- `docs/versions.md`
- `docs/diagrams/`
- `docs/adr/`
- `docs/runbooks/`
- `docs/acceptance/`
- `docs/debt-register.md`
- `contracts/state-machines.yaml`
- `contracts/features.toml`
- `contracts/schemas/`
- `contracts/openapi/audit.yaml`
- `contracts/openapi/ingestion.yaml`
- `contracts/openapi/retrieval.yaml`
- `contracts/openapi/generation.yaml`
- `contracts/openapi/citation-validator.yaml`
- `contracts/events/audit_*`  (files starting with this prefix)
- `contracts/events/ingestion_*`  (files starting with this prefix)
- `contracts/events/retrieval_*`  (files starting with this prefix)
- `contracts/events/validation_*`  (files starting with this prefix)
- `PATCH_WORKFLOW.md`
- `AGENTS.md`
- `logs/`

## Coordinator-owned (read-only for all developers)

- `OWNERSHIP.md`
- `CODEOWNERS`
- `docs/design/`
- `docs/compliance/`

## Shared write surface

- `status/SHARED_STATUS.md`: each collaborator edits only their own update block; anyone may append comments under comments blocks.

## Roles from the MVP report (section 11.1)

| MVP report role (section 11.1) | Who | Note |
| --- | --- | --- |
| Product owner | The coordinator (human) | Scope, acceptance sign-off, flag decisions |
| Security lead | Daniel | Reviews `db/policies/`, key controls, authorization matrix, isolation suite results |
| Tech lead & Release manager | Ganpati | Architecture conformance, ADRs, gatekeeper, attestations, M1a tags |
| QA and automation lead | Ganpati | Acceptance run, Playwright and provenance tooling, run report |
| Data steward | Ganpati | Corpus manifest, licences, allow-list |
| Domain reviewers (an attorney and a clinician) | Named humans outside the projects | Question sets, unanswerable questions, 100 labeled pairs per domain |

A role gives responsibility and a duty to answer questions. It never gives authority to edit another collaborator's files.

## Project execution across phases

| Phase | Primary owner | Contributing |
| --- | --- | --- |
| P0 Foundation | Ganpati | Daniel (Auth0, AWS, harness) |
| P1 Data layer and keys | Ganpati (schema, RLS, audit chain), Daniel (keys, KeyGuard) | Ganpati (fixtures) |
| P2 Identity and gateway | Daniel | Ganpati (state-machine tests, support, e2e) |
| P3 Ingestion | Ganpati | Daniel (keys) |
| P4 Retrieval, generation, validation | Ganpati | Daniel (Gateway wiring) |
| P5 Frontend, audit, alerts | Ganpati | Daniel (two alerts) |
| P6 Acceptance and run report | Ganpati | Daniel; Ganpati signs attestations and cuts M1a tag |

## Coordinator decisions needed (defaults confirmed)

| ID | Decision | Status |
| --- | --- | --- |
| CD-1 | Coordinator role and ownership change tracking | A named person; commit to this file with `Ownership-Change` trailer |
| CD-2 | Release line and main branch | Single `main` branch with automated pipeline checks |
| CD-3 | Data and key layer split | Schema, RLS, audit to Ganpati; keys, KMS, KeyGuard to Daniel |
| CD-4 | Layout additions | `libs/lmqa_release` and embedding wrappers accepted |
| CD-5 | Policy oracle | Labeled instruments against scratch DB |
| CD-6 | Stage assignments | Assigned to earliest stages in `stages.toml` |
| CD-7 | Lockfile ownership | Ganpati maintains `uv.lock` |
| CD-8 | Knowledge sync | Main repository sync |
| CD-9 | Team-process files | `logs/` and `status/` allowed |
| CD-10 | Observability stack | Structured redacted logging |
| CD-12 | Scope cuts | M1a cut list approved |
| CD-13 | Object store | Real AWS S3 in all environments |
