/**
 * The Auth0 client (doc 8.3, G8.5). Built lazily so a missing setting cannot break `next build`; the
 * first request that needs it fails with a clear message instead.
 *
 * - Authorization Code with PKCE, "Regular Web Application" client (doc 8.2).
 * - Server-side Valkey session store: the browser holds an opaque httpOnly cookie only.
 * - `enableAccessTokenEndpoint: false`: the SDK's default would expose the access token to the browser.
 * - Default audience is the ONBOARDING API (no organization). Once a membership exists the BFF starts a
 *   new authorization request naming the organization and the main audience (doc 7.1, step 4).
 */
import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { usable, ValkeySessionStore, valkey } from "@/lib/session-store";

function required(name: string): string {
  const value = usable(process.env[name]);
  if (!value) throw new Error(`${name} is not set (see .env.example)`);
  return value;
}

export const audiences = {
  get main(): string {
    return required("AUTH0_AUDIENCE_MAIN");
  },
  get onboarding(): string {
    return required("AUTH0_AUDIENCE_ONBOARDING");
  },
};

let client: Auth0Client | undefined;

export function getAuth0(): Auth0Client {
  client ??= new Auth0Client({
    domain: required("AUTH0_DOMAIN"),
    clientId: required("AUTH0_CLIENT_ID_BFF"),
    clientSecret: required("AUTH0_CLIENT_SECRET_BFF"),
    appBaseUrl: required("APP_BASE_URL"),
    secret: required("AUTH0_SESSION_SECRET"),
    sessionStore: new ValkeySessionStore(valkey(), required("AUTH0_SESSION_SECRET")),
    session: { rolling: true, inactivityDuration: 15 * 60, absoluteDuration: 8 * 3600 }, // privileged limits
    authorizationParameters: { audience: audiences.onboarding, scope: "openid profile email offline_access" },
    enableAccessTokenEndpoint: false,
    signInReturnToPath: "/",
  });
  return client;
}

/** The `aud` of a JWT, read without verification (it came from Auth0 through our own session). */
export function audienceOf(token: string): string | null {
  try {
    const payload = JSON.parse(Buffer.from(token.split(".")[1] ?? "", "base64url").toString("utf8")) as { aud?: string | string[] };
    return Array.isArray(payload.aud) ? (payload.aud[0] ?? null) : (payload.aud ?? null);
  } catch {
    return null;
  }
}
