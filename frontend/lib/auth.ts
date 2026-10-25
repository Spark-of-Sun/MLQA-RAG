import { betterAuth } from "better-auth";
import { genericOAuth } from "better-auth/plugins";
import { nextCookies } from "better-auth/next-js";
import Database from "better-sqlite3";

const oauthScopes = (process.env.OAUTH_SCOPES ?? "openid profile email")
  .split(" ")
  .filter(Boolean);

export const auth = betterAuth({
  // Local-dev session store, same "local substitute" pattern the backend
  // uses everywhere else (docs/architecture.md §8) — swap for a Postgres
  // adapter once db/migrations exists; nothing above this line changes.
  database: new Database(process.env.AUTH_DB_PATH ?? "./auth.db"),

  plugins: [
    // The user's own OAuth 2.0 / OIDC provider — not a named built-in
    // (Google, GitHub, ...), so it's registered through Better Auth's
    // Generic OAuth plugin. See .env.local.example for every variable
    // this reads, and app/login/login.md for the full sign-in flow.
    genericOAuth({
      config: [
        {
          providerId: process.env.OAUTH_PROVIDER_ID ?? "legalmed-oauth",
          clientId: process.env.OAUTH_CLIENT_ID ?? "",
          clientSecret: process.env.OAUTH_CLIENT_SECRET,
          // Preferred path: OIDC discovery resolves the three endpoints
          // below automatically. Only set them by hand if your provider
          // doesn't publish a discovery document.
          discoveryUrl: process.env.OAUTH_DISCOVERY_URL,
          authorizationUrl: process.env.OAUTH_AUTHORIZATION_URL,
          tokenUrl: process.env.OAUTH_TOKEN_URL,
          userInfoUrl: process.env.OAUTH_USERINFO_URL,
          scopes: oauthScopes,
        },
      ],
    }),

    // Lets server actions (not just route handlers) set the session
    // cookie. Must stay last in this array per Better Auth's docs.
    nextCookies(),
  ],
});

export type Session = typeof auth.$Infer.Session;
