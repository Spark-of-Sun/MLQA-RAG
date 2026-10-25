# Dashboard — `/dashboard`

## Purpose

The signed-in home. By explicit scope decision, this phase ships it as a
**minimal shell only** — the persistent nav frame and a welcome message.
Overview stats, the Q&A launcher, and the document/audit summaries this
page will eventually hold are not built yet.

## Files

| File | Role |
|---|---|
| `app/dashboard/page.tsx` | The page itself (server component) |
| `components/sign-out-button.tsx` | Client component that ends the session |
| `proxy.ts` | Route guard that runs before this page renders |
| `lib/auth.ts` | Better Auth server config, used for the session check below |

## Endpoints involved

| Endpoint | Called by | What it does |
|---|---|---|
| `GET /api/auth/get-session` | `auth.api.getSession()` inside `page.tsx` | Full, server-side session validation (not just a cookie check) |
| `POST /api/auth/sign-out` | `authClient.signOut()` in `sign-out-button.tsx` | Clears the session cookie; if the OAuth provider supports RP-Initiated Logout and was configured with `OAUTH_DISCOVERY_URL`, also redirects to the provider's logout endpoint |

**No backend Gateway endpoints are called from this page yet.** Once the
Ask / Library / Audit views are built, this page is where their summaries
will likely be pulled from — `GET /v1/documents`, `GET /v1/audit`, etc.,
per `docs/api-contracts/gateway.yaml` — but that's next-phase work, not
guessed at here. See the "Known gap" note in `app/login/login.md` first:
the Gateway needs its own `tenant_id`/`RoleScope` for this person before
any of those calls can be scoped correctly.

## Workflow

1. Browser requests `/dashboard` (or any `/dashboard/*` path).
2. `proxy.ts` runs first (Next.js 16's replacement for `middleware.ts`).
   It only checks whether a Better Auth session **cookie is present** —
   no database call, so it's fast. No cookie → redirect to `/login`.
   This is an optimistic check; it does not prove the cookie is valid.
3. If the cookie exists, the request reaches `page.tsx`, which calls
   `auth.api.getSession()` — this one DOES hit the database/session
   store. A forged or expired cookie fails here and gets redirected to
   `/login`, even though step 2 let it through. This two-step pattern
   (cheap check at the edge, real check at the page) is Better Auth's own
   documented recommendation, not an improvised shortcut.
4. With a valid session, the shell renders: product name, a nav list
   (all items but "Overview" are placeholders — `href="#"`, intentionally
   inert until their pages exist), the person's name/email, and a
   "Sign out" control.
5. The main panel shows a one-line welcome and an empty-state panel.
   Nothing here is clickable yet.
6. Clicking "Sign out" calls `authClient.signOut()`, then routes back to
   `/login` and refreshes the router cache so a back-navigation doesn't
   show a stale authenticated view.

## Design notes

Left sidebar (fixed width, hairline right border) + content area — no
cards, no shadows. The active nav item is marked with a 2px accent-blue
left border, the only accent-colored element on the page. Placeholder nav
items are visually present but clearly inert (muted text, `href="#"`) so
the shell communicates "more is coming" without pretending those sections
work.
