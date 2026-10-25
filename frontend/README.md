# Lexdoc — Frontend

Minimal, two-page scaffold for the Legal/Medical Document Q&A system's
frontend: **Login** and **Dashboard** only. Everything else in
`docs/architecture.md`'s `frontend/` layout (chat workspace, document
library, audit view, admin console) is intentionally not built yet.

Each page documents its own endpoints and workflow next to its code:

- [`app/login/login.md`](./app/login/login.md)
- [`app/dashboard/dashboard.md`](./app/dashboard/dashboard.md)

Running history of what changed and why: [`frontend-progress.md`](./frontend-progress.md).

## Stack

| Layer | Choice | Version at time of writing |
|---|---|---|
| Framework | Next.js (App Router) | 16.4.2 |
| UI library | React | 19.3.1 |
| Language | TypeScript | 6.0.3 |
| Styling | Tailwind CSS (CSS-first config) | 4.3.3 |
| Auth | Better Auth + Generic OAuth plugin | 1.7.12 |
| Local session store | SQLite via `better-sqlite3` | 13.0.3 |

All five were installed at their current `latest` npm tag — see
`frontend-progress.md` for why Better Auth was chosen over NextAuth/Auth.js.

## Prerequisites

- Node.js ≥ 20.9 (developed and tested on Node 22)
- An OAuth 2.0 / OIDC application already registered with your provider —
  you'll need its domain (or discovery URL), client ID, and client secret

## Setup

```bash
npm install
cp .env.local.example .env.local
# fill in .env.local — see app/login/login.md for exactly which values
# are required and the redirect URI to register with your provider

npm run auth:generate   # creates/updates the Better Auth schema definition
npm run auth:migrate    # applies it to the local SQLite file (AUTH_DB_PATH)

npm run dev
```

Then open http://localhost:3000 — it redirects to `/login` when signed
out, `/dashboard` when signed in.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Start the dev server (Turbopack) |
| `npm run build` | Production build |
| `npm run start` | Run a production build |
| `npm run lint` | ESLint |
| `npm run auth:generate` | Regenerate Better Auth's schema after changing `lib/auth.ts` |
| `npm run auth:migrate` | Apply the schema to the local SQLite file |

## Project layout

```
frontend/
├── app/
│   ├── layout.tsx          # fonts, metadata
│   ├── globals.css         # Tailwind v4 theme — the black/white/blue tokens
│   ├── page.tsx             # redirects to /login or /dashboard
│   ├── login/
│   │   ├── page.tsx
│   │   └── login.md
│   ├── dashboard/
│   │   ├── page.tsx
│   │   └── dashboard.md
│   └── api/auth/[...all]/route.ts   # Better Auth's endpoints
├── components/
│   ├── sign-in-button.tsx
│   └── sign-out-button.tsx
├── lib/
│   ├── auth.ts              # Better Auth server config (OAuth provider lives here)
│   ├── auth-client.ts       # Better Auth browser client
│   └── site.ts              # product name/tagline — the one placeholder to rename
├── proxy.ts                 # Next.js 16's route guard (was middleware.ts)
├── frontend-progress.md
└── .env.local.example
```

## Not built yet (by scope, not oversight)

- Ask / Library / Audit / Admin pages and nav
- Any call into the backend Gateway (`services/gateway`) — this frontend's
  session is currently local to itself only; see the "Known gap" note in
  `app/login/login.md`
- A production-grade (non-SQLite) session store
