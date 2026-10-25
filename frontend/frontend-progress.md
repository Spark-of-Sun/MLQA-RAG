# Frontend Progress Log

Dated entries, newest first. Each entry says what changed, what was
decided, and why — so a later session (human or otherwise) doesn't have
to re-derive these choices from the diff alone.

---

## 2026-10-22 — Initial scaffold: Login + Dashboard

Full restart of the frontend per instruction, built from
`docs/architecture.md` / the system-design PDF rather than any prior
frontend work. Scope for this pass: **Login and Dashboard only** — every
other view in the architecture doc's `frontend/` layout (chat workspace,
document library, audit view, admin console) is deliberately out of
scope here.

### Stack decisions

All dependencies were installed fresh at their current npm `latest` tag
(resolved 2026-10-22):

| Package | Version | Why this one |
|---|---|---|
| `next` | 16.4.2 | Current stable major (16.x); App Router throughout |
| `react` / `react-dom` | 19.3.1 | Bundled/required by Next 16 |
| `typescript` | 6.0.3 | Current major |
| `tailwindcss` + `@tailwindcss/postcss` | 4.3.3 | Current major; CSS-first config (`@theme` in `globals.css`, no `tailwind.config.js`) |
| `better-auth` | 1.7.12 | See below |
| `better-sqlite3` | 13.0.3 | Local session store — see below |
| `eslint` | 9.39.5 | Pinned one line below npm's own `latest` tag (10.x) because `eslint-config-next@16.4.2`'s peer range doesn't yet cover ESLint 10. This is `eslint-config-next`'s constraint, not a stale choice on our part — revisit when Next ships a config package that supports it. |

**Why Better Auth instead of NextAuth/Auth.js**, since
`docs/architecture.md` only says "NextAuth/Auth.js": as of this writing,
Auth.js v5 — the version with proper App Router support — is still on
the `beta` npm tag (`5.0.0-beta.32`), and Auth.js's own maintainers
(maintenance passed to the Better Auth team in Sept 2025) point new
projects at Better Auth rather than Auth.js v4 or v5. Better Auth is
stable (1.7.x), and its **Generic OAuth plugin** is a direct fit for "I
already have a domain, client ID and secret for my own OAuth provider" —
it supports both OIDC discovery and fully manual endpoint configuration.
If this turns out wrong for the team's needs, `lib/auth.ts` is the only
file that would need to change; nothing in `app/` calls a provider SDK
directly.

**Why SQLite (`better-sqlite3`) for the session store**: Better Auth
needs *some* database for users/sessions/accounts, and `db/migrations`
(the real Postgres schema, per `docs/architecture.md` §9 milestone 6)
doesn't exist yet. A local SQLite file is the same "local substitute"
pattern the backend already uses everywhere (`docs/architecture.md` §8 —
MinIO for S3, local Qdrant for managed Qdrant, etc.), so this isn't a new
pattern, just the frontend's version of one already in the repo. Swapping
to Postgres later is a one-line change to the `database:` option in
`lib/auth.ts` (Better Auth supports a `pg.Pool` directly) — nothing else
in this scaffold depends on it being SQLite specifically.

**Why Next.js 16's `proxy.ts` instead of `middleware.ts`**: Next 16
renamed the file/export; `middleware.ts` would just error on this
version. Not a style choice — it's what the installed Next version
requires.

### Design brief

The two pages requested so far:

- **Color** — `#FFFFFF` canvas, `#0B0F14` ink (near-black, intentionally
  cool rather than literal `#000` — reads as precise/clinical rather than
  flat), `#52606D` soft ink for secondary text, `#E2E5E9` hairline, one
  accent `#1D4ED8` (a confident, unsaturated blue — trust without looking
  like a generic SaaS electric-blue), `#1E3A8A` for its hover state. No
  other colors. The accent is spent in exactly one place per screen: the
  primary action on Login (the sign-in button), the active nav indicator
  on Dashboard.
- **Type** — two families, clearly distinct roles: **Public Sans** (built
  for U.S. federal digital-service clarity — a deliberate nod to this
  product's compliance/regulatory subject matter) for every working UI
  surface; **Source Serif 4**, reserved only for the wordmark and page
  titles, echoing the contract/clinical-note heritage of what this system
  reads.
- **Layout** — flat hairline borders, no drop shadows, no rounded-card
  treatment, no gradients. Login is a single centered bordered panel;
  Dashboard is a fixed sidebar + content area. Zero border-radius
  throughout — a deliberate, legal-document-ledger choice, not a default.
- **Principles** — precision over decoration (every border marks a real
  boundary, never decoration); the one accent color is spent sparingly;
  serif is identity/headline only, never body text; no motion beyond
  functional hover/focus transitions.

### What shipped

- `app/login/page.tsx` + `login.md`
- `app/dashboard/page.tsx` + `dashboard.md`
- `lib/auth.ts`, `lib/auth-client.ts`, `app/api/auth/[...all]/route.ts`,
  `proxy.ts` — full Better Auth wiring, generic OAuth provider driven
  entirely by env vars (see `.env.local.example`)
- `app/globals.css` — the token system above, as Tailwind v4 `@theme`
- Root `app/page.tsx` redirect, root `README.md`, this log

### Validation performed

`npm run lint` and `npm run build` were both run against this exact
scaffold before delivery. Lint is clean. The build compiles, type-checks,
and generates all five routes correctly (`/`, `/login`, `/dashboard`,
`/api/auth/[...all]`, the `Proxy`). One caveat specific to the sandbox
this was built in, not to the code: its outbound network is allow-listed
to package registries only, so `next/font/google`'s fetch to
`fonts.googleapis.com` was unreachable there. That step was verified
separately by swapping `app/layout.tsx` to system fonts, confirming the
rest of the build was clean, then restoring the real Google Fonts
version shown in the delivered files. A normal dev machine or CI runner
with ordinary internet access will fetch the fonts at build time with no
changes needed. `tsconfig.json`'s `baseUrl` was also dropped — TypeScript
6.0 flags it as deprecated under `moduleResolution: "bundler"`, and
`paths` resolves fine without it.

### Known gaps (not fixed in this pass)

- **No bridge to the backend Gateway's session.** This frontend's auth is
  self-contained (Better Auth + its own SQLite store). The Gateway
  (`services/gateway`) has an entirely separate session model —
  `SessionClaims` JWT with `tenant_id` and `RoleScope[]`
  (`libs/common/auth/jwt.py`) — that nothing here produces yet. Flagged
  in detail in `app/login/login.md`; needs a real decision (not a guess)
  before the Ask/Library/Audit views can call the Gateway as this
  person.
- OAuth callback errors (`?error=...`) aren't surfaced to the person yet
  — only client-side JS/network failures show a message.
- No test coverage yet (no test runner installed in this pass either).
- Lint/build were run against this scaffold before delivery; see the
  commands in `README.md` to re-verify after changes.

### Next candidates (not started)

In the order the build-order milestones in `docs/architecture.md` §9
would suggest: wire a real tenant/role source for the Gateway bridge,
then Ask (chat workspace), then Library, then Audit, then Admin.
