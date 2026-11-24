import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { NextResponse } from "next/server";

import { sessionStoreFromEnv } from "@/lib/session-store";

// Auth0 authenticates; the gateway and PostgreSQL authorize (blueprint 1.2, 8).
// Tokens never reach the browser: the access-token endpoint is disabled and the session cookie is
// encrypted with AUTH0_SESSION_SECRET (blueprint 17.3, G8.5).
const domain = (process.env.AUTH0_DOMAIN ?? "").replace(/^https?:\/\//, "").replace(/\/$/, "");
export const APP_BASE_URL = (process.env.APP_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

/** Only same-site paths: "/x" yes, "//evil.example" or "https://…" no. */
function safePath(path: string | undefined): string {
  return path && path.startsWith("/") && !path.startsWith("//") ? path : "/home";
}

export const auth0 = new Auth0Client({
  domain,
  clientId: process.env.AUTH0_CLIENT_ID_BFF,
  clientSecret: process.env.AUTH0_CLIENT_SECRET_BFF,
  secret: process.env.AUTH0_SESSION_SECRET,
  appBaseUrl: APP_BASE_URL,
  signInReturnToPath: "/home",
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE_MAIN,
    scope: "openid profile email",
  },
  session: {
    rolling: true,
    inactivityDuration: 30 * 60,
    absoluteDuration: 8 * 60 * 60,
  },
  enableAccessTokenEndpoint: false,
  // Server-side sessions (G8.5): with a store, the cookie carries only an opaque ID.
  sessionStore: sessionStoreFromEnv(),
  // The SDK's default shows a bare 500 page with the error text. Send the user back to the start page with a
  // short reason instead, so a stale or replayed callback (back button, reload, expired attempt) is one click
  // to recover from. Auth0 errors such as access_denied keep their code for diagnosis.
  async onCallback(error, ctx) {
    const base = ctx.appBaseUrl ?? APP_BASE_URL;
    if (error) {
      const cause = (error as { cause?: { code?: string } }).cause?.code;
      const code = cause ?? error.code ?? "callback_error";
      console.warn(`auth callback failed: ${code}`);
      return NextResponse.redirect(new URL(`/?auth_error=${encodeURIComponent(code)}`, base));
    }
    return NextResponse.redirect(new URL(safePath(ctx.returnTo), base));
  },
});
