# legal-medical-qa (MVP)

Questions over legal and medical documents, answered only with machine-verified, page- and clause-level citations.
Unsupported sentences are removed before anyone sees them; when the documents do not answer, the system refuses.
Design: `project-blueprint/` (v3.1). What this MVP builds, and what it defers, is in [docs/mvp.md](docs/mvp.md);
the production build and its status (written, switched on, proven) is in [docs/production.md](docs/production.md).
The product is called **Cyte** (by Onekami); the customer guide is [docs/user-guide.md](docs/user-guide.md).
The public website (Home, Product, Industries, Security, Pricing, Docs, Company, Contact) is served by the same
Next.js app, in `frontend/src/app/(site)/`. The docs at `/docs` are written from the blueprint
(`frontend/src/lib/docs.ts`): public pages for everyone, the rest only for the roles they concern (a Super Admin reads
all; an admin reads admin and member pages; a member reads member pages). Access is decided on the server from the
gateway's role, and a page you may not read shows a lock on the page itself, nowhere else.

Deploying to https://onekami.site (Cloudflare Workers for the website, a Linode with Docker and a Cloudflare Tunnel
for the API, local embeddings) is described in [docs/deploy.md](docs/deploy.md), on the `deployed` branch.

## Run it on localhost

Prerequisites: Docker (your user in the `docker` group), [uv](https://docs.astral.sh/uv/), Node 24 and pnpm.

1. **Settings.** Put your Auth0 and Gemini values in `.env`. `example-env.txt` in the repo root lists every setting
   with placeholders (it is kept on your machine and not committed; ask a teammate for a copy);
   `make doctor` names any setting that is missing. Local-only secrets (database passwords, join-code pepper,
   session secret) are generated for you.
   **Answer model:** set `LLM_PROVIDER` and `LLM_MODEL` in `.env` and restart; no code change. Providers: `gemini`
   (default), `anthropic`, `openai`, `groq`, `openrouter`, `deepseek`, `mistral`, `together`, `ollama` (local),
   or `openai_compatible` with `LLM_BASE_URL`. Set the provider's key (for example `GROQ_API_KEY`).
   `LLM_FALLBACK_MODELS` may mix providers: `gemini-3.5-flash-lite,anthropic:<model>`. Embeddings always use
   Gemini, so `GEMINI_API_KEY` is required whichever provider answers.
2. **Auth0 dashboard** (once):
   - Applications → your *Regular Web Application*:
     Allowed Callback URLs `http://localhost:3000/auth/callback`, Allowed Logout URLs `http://localhost:3000`,
     Allowed Web Origins `http://localhost:3000`.
   - Applications → APIs: an API whose *Identifier* equals `AUTH0_AUDIENCE_MAIN`, signing algorithm RS256.
3. **Start:**

   ```sh
   make setup     # dependencies, local secrets, PostgreSQL 18 + pgvector in Docker, migrations
   make doctor    # checks settings, database, Auth0, the answer models and embeddings; prints names, never values
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
   highlighted passage; open *verification details* to see each check. Ask a follow-up in the same chat ("and what
   must the Executive sign first?"): it is understood from the conversation, and the answer is still checked against
   the documents. Ask something the documents do not cover to see the refusal.
   Chats work like any chat app: the sidebar lists your chats (renamable, deletable), **New chat** starts a fresh
   one, and opening a chat continues where you left off. Chats are private to their author, even from the admin.
6. **Manage members → Generate code** to invite a member. A member's uploads are private unless they tick
   **Share with my workspace admin**; the admin shares each upload with the whole workspace, with selected members,
   or with no one. The Library's Access column says who shared each document. Manage members shows each member's
   documents, documents shared with you, questions asked and approximate tokens; click a member for their profile.
7. **Profile** lets everyone edit their name, job title, department and phone. **Audit trail** has sections per role
   (a member: All activity, Library, Chats) with filters for event, person, dates and free text; the filters are
   kept in the URL. **Verify hash chain** works for every role.

## Verify without a browser

```sh
make demo       # 94 checks: onboarding A/B/C, approvals, uploads, sharing, RLS isolation, cited answers, refusals,
                # chats, profiles, audit sections and filters, suspension, audit chain and tamper detection;
                # real Gemini, separate lmqa_demo database
make demo-web   # 56 checks: signed-in browsers against the built frontend (role routing, 404s, BFF, CSP,
                # no tokens in pages, docs access by role); run `make build` first
make eval       # retrieval quality on the public corpus (recall@k, MRR, nDCG, abstention) for three
                # pipeline configurations, checked against eval/floors.toml; ARGS=--answers adds end-to-end answers
make lint       # ruff format + ruff check + TypeScript
```

Nothing is simulated, sign-in included. `make demo`, `make demo-web` and `make eval` use real accounts in the
Auth0 tenant; no local key signs tokens. They need `AUTH0_DOMAIN`, `AUTH0_AUDIENCE_MAIN`, `AUTH0_CLIENT_ID_HARNESS`
and `AUTH0_CLIENT_SECRET_HARNESS`, and each account signed in once through Universal Login with the auth harness:

```sh
uv run python tools/auth_harness.py serve &
uv run python tools/auth_harness.py url --label demo-alice   # open the URL and sign in as that account
```

Labels: `demo-alice`, `demo-bob`, `demo-carol`, `demo-dave`, `demo-erin`, `demo-frank` (`make demo`),
`demo-newcomer` (`make demo-web`), `eval-owner`, `eval-admin` (`make eval`). The stored refresh token keeps each
session alive (`tools/real_identity.py`); a missing variable or label stops the command with a message naming it.

## Layout (blueprint 18)

```
contracts/      authz-matrix.yaml (route allow-list; the gateway refuses to start on drift), state-machines.yaml
db/             migrations/ (schema), policies/ (RLS, helpers, audit chain), roles/ (grants)
libs/           lmqa_models  lmqa_db  lmqa_audit  lmqa_auth  lmqa_security  lmqa_vectorstore  lmqa_objectstore
services/       gateway  identity  ingestion  retrieval  generation  citation_validator  audit
prompts/        templates/, few_shot_examples/, registry.toml (hashed into every answer's audit record)
frontend/       Next.js 16: src/proxy.ts, src/app/(site) public website, (onboarding|app|account|super-admin|
                workspace-admin) product screens, api/backend (BFF); public/ icons and the Onekami logo
corpus/         manifest.toml (URL, licence, SHA-256) and fetchers.py; data/ is fetched, not committed
tools/          doctor, gen_env, db_migrate, load_corpus, dev, demo, demo_web, real_identity, auth_harness, withenv
```

`make help` lists every target. `make db-reset` deletes all local data and starts with an empty database.
