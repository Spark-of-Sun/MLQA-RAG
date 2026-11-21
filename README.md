# legal-medical-qa (MVP)

Questions over legal and medical documents, answered only with machine-verified, page- and clause-level citations.
Unsupported sentences are removed before anyone sees them; when the documents do not answer, the system refuses.
Design: `project-blueprint/` (v3.0). What this MVP builds, and what it defers, is in [docs/mvp.md](docs/mvp.md).

## Run it on localhost

Prerequisites: Docker (your user in the `docker` group), [uv](https://docs.astral.sh/uv/), Node 24 and pnpm.

1. **Settings.** Put your Auth0 and Gemini values in `.env`; `make doctor` names any setting that is missing.
   Local-only secrets (database passwords, join-code pepper, session secret) are generated for you.
2. **Auth0 dashboard** (once):
   - Applications → your *Regular Web Application*:
     Allowed Callback URLs `http://localhost:3000/auth/callback`, Allowed Logout URLs `http://localhost:3000`,
     Allowed Web Origins `http://localhost:3000`.
   - Applications → APIs: an API whose *Identifier* equals `AUTH0_AUDIENCE_MAIN`, signing algorithm RS256.
3. **Start:**

   ```sh
   make setup     # dependencies, local secrets, PostgreSQL 18 + pgvector in Docker, migrations
   make doctor    # checks settings, database, Auth0 and Gemini; prints names, never values
   make start     # production build; app on http://localhost:3000, API on http://127.0.0.1:8000
   ```

   `make dev` runs the same with hot reload. Ctrl+C stops both processes.

## Demo walkthrough (about 5 minutes)

1. Open http://localhost:3000 → **Get started** → sign up → **Create an organization**. You are its Super Admin.
2. **Manage admins → Generate code.** Copy the invite link (the code is shown once).
3. In a private window, open the link, sign up with a second account and send the join request; approve it in
   the first window. The second account now runs a workspace.
4. As that admin: `make corpus` (downloads the real public documents, SHA-256 checked), then
   `make load-corpus EMAIL=<admin email> DOMAIN=legal` (or upload files in **Library**).
5. **Ask**: for example "When must the severance benefit be paid?". Click a citation number to see the exact
   highlighted passage; open *verification details* to see each check. Ask something the documents do not cover
   to see the refusal.
6. **Manage members → Generate code** to invite a member; members upload private documents that even the admin
   cannot see. **Audit trail → Verify hash chain** shows the tamper-evident log.

## Verify without a browser

```sh
make demo       # 50 checks: onboarding A/B/C, approvals, uploads, RLS isolation, cited answers, refusals,
                # suspension, audit chain and tamper detection; real Gemini, separate lmqa_demo database
make demo-web   # 21 checks: signed-in browsers against the built frontend (role routing, 404s, BFF, CSP,
                # no tokens in pages); run `make build` first
make lint       # ruff format + ruff check + TypeScript
```

Only the Auth0 login is simulated in these two scripts (tokens signed by a throwaway local key, verified by the
same gateway code). Everything else is real: PostgreSQL row-level security, the public corpus, Gemini and the
citation validator.

## Layout (blueprint 18)

```
contracts/      authz-matrix.yaml (route allow-list; the gateway refuses to start on drift), state-machines.yaml
db/             migrations/ (schema), policies/ (RLS, helpers, audit chain), roles/ (grants)
libs/           lmqa_models  lmqa_db  lmqa_audit  lmqa_auth  lmqa_security  lmqa_vectorstore  lmqa_objectstore
services/       gateway  identity  ingestion  retrieval  generation  citation_validator  audit
prompts/        templates/, few_shot_examples/, registry.toml (hashed into every answer's audit record)
frontend/       Next.js 16: src/proxy.ts, src/app/(onboarding|app|super-admin|workspace-admin), api/backend (BFF)
corpus/         manifest.toml (URL, licence, SHA-256) and fetchers.py; data/ is fetched, not committed
tools/          doctor, gen_env, db_migrate, load_corpus, dev, demo, demo_web, withenv
```

`make help` lists every target. `make db-reset` deletes all local data and starts with an empty database.
