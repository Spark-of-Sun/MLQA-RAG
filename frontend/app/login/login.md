# Login — `/login`

## Purpose

Single entry point for authentication. Shows one action: sign in through
the organization's OAuth / OIDC provider. There is no email/password form —
this phase only wires up the OAuth provider the person already has a
domain, client ID and secret for.

## Files

| File | Role |
|---|---|
| `app/login/page.tsx` | The page itself (server component) |
| `components/sign-in-button.tsx` | Client component that starts the OAuth redirect |
| `lib/auth.ts` | Better Auth server config — the OAuth provider is registered here |
| `lib/auth-client.ts` | Better Auth browser client used by the button |
| `app/api/auth/[...all]/route.ts` | Catches every Better Auth endpoint, including the OAuth callback |
| `proxy.ts` | Not involved in showing this page, but see **Workflow** below |

## Endpoints involved

All authentication endpoints are mounted by Better Auth under
`/api/auth/*` (via `app/api/auth/[...all]/route.ts`). This page's flow
touches three of them:

| Endpoint | Called by | What it does |
|---|---|---|
| `POST /api/auth/sign-in/social` | `authClient.signIn.social()` in `sign-in-button.tsx` | Starts the OAuth flow; returns the provider's authorization URL and redirects the browser there |
| `GET /api/auth/callback/<OAUTH_PROVIDER_ID>` | The OAuth provider, after the person approves access | Exchanges the authorization code for tokens, fetches the user's profile, creates/updates the local user record, sets the session cookie |
| `GET /api/auth/get-session` | `auth.api.getSession()` inside `page.tsx` (server-side, not a browser fetch) | Confirms whether a session already exists, so a signed-in person never sees this form again |

**This is not the backend Gateway.** None of the five Python services in
`docs/architecture.md` are called from this page. Better Auth's session is
local to the frontend only. Bridging it into a Gateway-recognized session
(the `SessionClaims` JWT described in `docs/architecture.md` §7) is not
built yet — see **Known gap** below.

## Workflow

1. Person opens `/login` (or `/`, which redirects here if signed out).
2. Server-side, the page calls `auth.api.getSession()`. If a valid session
   already exists, it redirects straight to `/dashboard` — the form never
   renders.
3. Otherwise the panel renders with one button, labeled by
   `NEXT_PUBLIC_OAUTH_PROVIDER_LABEL` (defaults to "Continue with SSO").
4. Clicking it calls `authClient.signIn.social({ provider, callbackURL: "/dashboard" })`,
   which redirects the browser to the provider's authorization URL.
5. The person authenticates with the provider and approves access.
6. The provider redirects back to
   `/api/auth/callback/<OAUTH_PROVIDER_ID>`. Better Auth exchanges the
   code, fetches the profile, upserts the user in the local SQLite store,
   and sets an HTTP-only session cookie.
7. The browser lands on `/dashboard` with that cookie already set.
8. `proxy.ts` (checked on every `/dashboard/*` request, including this
   first one) sees the cookie and lets the request through; the dashboard
   page then does its own full session check — see `app/dashboard/dashboard.md`.

If the OAuth exchange fails (bad client secret, mismatched redirect URI,
person denies consent, etc.), Better Auth redirects back with an `error`
query parameter rather than throwing; this page does not currently read
or display that parameter — it only catches a client-side network/JS
failure and shows a generic "Sign-in failed" message. Surfacing the real
`error` reason is a reasonable next step once this is wired to a real
provider.

## Required setup

Copy `.env.local.example` → `.env.local` and fill in:

- `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` — from your provider
- `OAUTH_DISCOVERY_URL` — your provider's `.well-known/openid-configuration`
  URL, **or** the three `OAUTH_AUTHORIZATION_URL` / `OAUTH_TOKEN_URL` /
  `OAUTH_USERINFO_URL` variables if it doesn't support OIDC discovery
- `BETTER_AUTH_SECRET` — any random 32+ character string

Then, in your OAuth provider's dashboard, register this exact redirect URI:

```
<BETTER_AUTH_URL>/api/auth/callback/<OAUTH_PROVIDER_ID>
# e.g. for local dev with the defaults in .env.local.example:
http://localhost:3000/api/auth/callback/legalmed-oauth
```

If the provider ID or base URL is wrong on either side, the callback will
404 or the provider will reject the redirect — this is the single most
common setup mistake with any OAuth integration.

## Known gap (flagged, not fixed here)

This phase only authenticates the person into the **frontend**. The
backend Gateway (`services/gateway`) has its own separate session model —
a short-lived JWT carrying `tenant_id` and `roles`
(`libs/common/auth/jwt.py`), currently minted only by the local-dev
`/v1/dev/session` endpoint. Nothing here calls the Gateway yet. Before the
Ask/Library/Audit views are built, something needs to decide how a Better
Auth session turns into a Gateway `SessionClaims` JWT (role/tenant/matter
assignment has to come from somewhere — Better Auth's OAuth profile alone
doesn't carry `tenant_id` or `RoleScope`). Worth deciding before the next
phase, not guessed at here.

## Design notes

One centered panel, hairline border, no shadow, no rounded corners — the
flat, document-literate look described in `frontend-progress.md`. The
accent blue is used in exactly one place on this page: the sign-in button.
